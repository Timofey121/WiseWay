import json
import logging
from contextlib import asynccontextmanager

from anyio import CapacityLimiter, to_thread
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from .audit import query_events
from .auth import Auth
from .common import ApiError, Settings, public, uid
from .contract import Contract
from .services import Context

READ_POSTS = {
    "searchFiles",
    "getSearchFacet",
    "querySortingQueue",
    "queryAuditEvents",
    "resolveTargetDirectory",
}
IDEMPOTENT = {"publishDictionary", "createSortingBatch"}
READ_ONLY = {
    "getAppConfig",
    "listRoots",
    "listCompanies",
    "searchFiles",
    "getSearchFacet",
    "listDictionaries",
    "getDictionary",
    "getDictionaryVersion",
    "getAuditUpdates",
    "queryAuditEvents",
    "querySortingQueue",
    "listAuditActors",
    "listQuarantineItems",
    "getSortingPreview",
    "getSortingBatch",
    "listSortingBatches",
    "listTargetDirectories",
    "resolveTargetDirectory",
    "listDictionaryVersions",
    "getSimulation",
}


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_unpaired_surrogates(value):
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise ValueError("unpaired surrogate")
        elif isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)


def create_app(settings=None):
    settings = settings or Settings()
    contract = Contract()

    @asynccontextmanager
    async def lifespan(app):
        app.state.ctx = Context(settings)
        app.state.auth = Auth(app.state.ctx.store, settings)
        # SQLite has one writer; a large thread pool causes lock contention and
        # competes for the GIL during metadata search/response validation.
        app.state.request_limiter = CapacityLimiter(4)
        # Slow search I/O must not occupy every session/audit/business slot.
        app.state.search_limiter = CapacityLimiter(4)
        yield
        app.state.ctx.close()

    app = FastAPI(
        title="Wise Way", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.contract = contract
    app.openapi = lambda: contract.spec
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    def execute(operation, path_item, request, body, request_id):
        ctx, auth = app.state.ctx, app.state.auth
        name = operation["operationId"]
        token = request.cookies.get("wiseway_session")
        session = actor = None
        if name == "login":
            auth.origin(request.headers)
        elif name != "getHealth":
            session, actor = auth.authenticate(token)
            if request.method in ("POST", "PUT", "PATCH", "DELETE") and name not in READ_POSTS:
                auth.csrf(request.headers, session)
        params = contract.request(
            operation, path_item, request.path_params, request.query_params, request.headers, body
        )
        response_headers = {}
        cookie = None
        validated = False
        if name == "getHealth":
            status, data = 200, {"status": "ok"}
        elif name == "login":
            data, cookie = auth.login(body, request_id, request.client.host if request.client else "local")
            status = 200
        elif name == "getSession":
            session["touched"] = settings.clock()
            status, data = 200, auth.dto(session, actor)
        elif name == "logout":
            auth.logout(token, actor, request_id)
            status, data = 204, None
        elif name == "returnQuarantineItem":
            from .quarantine import QuarantineService

            status, data = QuarantineService(ctx).return_item(actor, params, body, request_id)
        else:
            with ctx.store.transaction(write=name not in READ_ONLY) as tx:

                def action():
                    return dispatch(ctx, tx, name, actor, params, body, request_id)

                if name in IDEMPOTENT:
                    # Dictionary ID is part of operation identity, not just the body hash.
                    identity = name + ":" + request.url.path
                    status, data = ctx.idempotent(
                        tx, identity, actor, params["Idempotency-Key"], body, action
                    )
                else:
                    status, data = action()
                contract.response(operation, status, data)
                validated = True
        if not validated:
            contract.response(operation, status, data)
        if actor and name != "logout":
            auth.touch(token)
        response = (
            Response(status_code=status)
            if status == 204
            else JSONResponse(data, status_code=status, headers=response_headers)
        )
        if cookie:
            response.set_cookie(
                "wiseway_session",
                cookie,
                httponly=True,
                secure=settings.secure_cookie,
                samesite="lax",
                path="/",
                max_age=settings.absolute_session_seconds,
            )
        if name == "logout":
            response.delete_cookie(
                "wiseway_session", path="/", httponly=True, secure=settings.secure_cookie, samesite="lax"
            )
        return response

    def endpoint(operation, path_item):
        async def handle(request: Request):
            request_id = uid("request")
            try:
                if request.url.hostname not in {
                    __import__("urllib.parse", fromlist=["urlparse"]).urlparse(o).hostname
                    for o in settings.allowed_origins
                }:
                    raise ApiError("FORBIDDEN", "Недопустимый адрес сервиса.", 403)
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        raise ApiError("VALIDATION_ERROR", "Слишком большой запрос.", 422)
                body = None
                if raw:
                    if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
                        raise ApiError("VALIDATION_ERROR", "Требуется application/json.", 422)
                    try:
                        body = json.loads(
                            bytes(raw).decode("utf-8"),
                            object_pairs_hook=_json_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                        )
                        _reject_unpaired_surrogates(body)
                    except (RecursionError, UnicodeDecodeError, ValueError):
                        raise ApiError("VALIDATION_ERROR", "Недопустимый JSON.", 422) from None
                response = await to_thread.run_sync(
                    execute,
                    operation,
                    path_item,
                    request,
                    body,
                    request_id,
                    limiter=(
                        app.state.search_limiter
                        if operation["operationId"] in {"searchFiles", "getSearchFacet"}
                        else app.state.request_limiter
                    ),
                )
            except ApiError as error:
                value = error.body(request_id)
                try:
                    contract.response(operation, error.status, value)
                except RuntimeError:
                    logging.getLogger("wiseway").error(
                        "Request failed request_id=%s exception=RuntimeError", request_id
                    )
                    error = ApiError("INTERNAL_ERROR", "Внутренняя ошибка сервиса.", 500)
                    value = error.body(request_id)
                response = JSONResponse(value, status_code=error.status)
                if error.status == 429:
                    response.headers["Retry-After"] = "60"
            except Exception as error:
                logging.getLogger("wiseway").error(
                    "Request failed request_id=%s exception=%s", request_id, type(error).__name__
                )
                response = JSONResponse(
                    ApiError("INTERNAL_ERROR", "Внутренняя ошибка сервиса.", 500).body(request_id),
                    status_code=500,
                )
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        return handle

    for path, item in contract.spec["paths"].items():
        for method, operation in item.items():
            if method in ("get", "post", "put", "patch", "delete"):
                app.add_api_route(
                    "/api/v1" + path,
                    endpoint(operation, item),
                    methods=[method.upper()],
                    name=operation["operationId"],
                )
    return app


def dispatch(ctx, tx, name, actor, params, body, request_id):
    if name == "getAppConfig":
        return 200, ctx.settings.app_config()
    if name == "listRoots":
        return 200, {
            "items": [
                public(json.loads(row[0]))
                for row in tx.connection.execute(
                    "SELECT json_extract(body, '$.root') FROM objects WHERE kind='index' ORDER BY id"
                )
            ]
        }
    if name == "listCompanies":
        return 200, {"items": [public(c) for c in tx.list("company")]}
    if name in ("searchFiles", "getSearchFacet"):
        from .search import search, facet

        root = tx.get("root", body["root_id"])
        if root is None or not root.get("_searchable"):
            raise ApiError("ROOT_NOT_READY", "Корень не опубликован.", 409)
        index = ctx.read_index(tx, body["root_id"])
        if index is None:
            raise ApiError("ROOT_NOT_READY", "Корень ещё индексируется.", 409)
        if index.get("_unavailable"):
            raise ApiError("SEARCH_UNAVAILABLE", "Поиск временно недоступен.", 503, retryable=True)
        if index.get("_storage") == "opensearch":
            from .opensearch import SearchSnapshot

            snapshot = SearchSnapshot(ctx.search_engine(), index)
            result = ctx.search_cache.get(
                (index["root"]["index_generation"], index["_pit_id"]),
                name,
                body,
                lambda: (
                    snapshot.search(body, ctx.settings.result_limit)
                    if name == "searchFiles"
                    else snapshot.facet(body)
                ),
            )
        elif index.get("_storage") == "sqlite":
            from .sqlite_search import SqlSearchIndex

            generation = tx.connection.execute(
                "SELECT root_id,state FROM search_generations WHERE generation_id=?",
                (index.get("_generation"),),
            ).fetchone()
            if (
                generation is None
                or generation[0] != body["root_id"]
                or generation[1] not in {"READY", "ACTIVE"}
            ):
                raise ApiError("SEARCH_UNAVAILABLE", "Поиск временно недоступен.", 503, retryable=True)
            prepared = SqlSearchIndex(tx, index["_generation"])
            result = (
                prepared.search(index["root"], body, ctx.settings.result_limit)
                if name == "searchFiles"
                else prepared.facet(index["root"], body)
            )
        else:
            prepared = ctx.prepared_search(index)
            result = (
                search(index["root"], index["items"], body, ctx.settings.result_limit, prepared=prepared)
                if name == "searchFiles"
                else facet(index["root"], index["items"], body, prepared=prepared)
            )
        if name == "searchFiles" and "freshness" in index:
            result["freshness"] = index["freshness"]
        return 200, result
    if name in ("queryAuditEvents", "getAuditUpdates", "listAuditActors"):
        from .audit_pagination import audit_actors, newest_visible_event_id

        if name == "getAuditUpdates":
            after = params.get("after_event_id")
            newest = newest_visible_event_id(tx, actor)
            return 200, {"has_new_events": newest is not None and newest != after}
        if name == "listAuditActors":
            items = audit_actors(tx, actor, params.get("prefix", ""))
            return 200, ctx.page(
                tx,
                name,
                actor,
                params,
                {"items": items},
                cursor=params.get("cursor"),
                limit=params.get("limit", 100),
            )
        if name == "queryAuditEvents":
            # Keep the validation seam lightweight: scalable audit pages query
            # SQLite directly, while pre-existing payload cursors retain their
            # historical in-memory snapshot behavior below.
            query_events(tx, actor, body, events=[])
            from .audit_pagination import is_sql_cursor, query_page

            if body["cursor"] is None or is_sql_cursor(tx, body["cursor"]):
                return 200, query_page(ctx, tx, actor, body)
            return 200, ctx.page(
                tx,
                name,
                actor,
                body,
                {"items": [], "newest_event_id": None},
                cursor=body["cursor"],
                limit=body["limit"],
            )
    if name == "listQuarantineItems":
        from .quarantine import QuarantineService

        return QuarantineService(ctx).list_items(tx, actor, params)
    if name in {
        "querySortingQueue",
        "createSortingSelection",
        "createSortingPreview",
        "getSortingPreview",
        "createSortingBatch",
        "getSortingBatch",
        "listSortingBatches",
    }:
        from .sorting import SortingService

        return SortingService(ctx).handle(name, tx, actor, params, body, request_id)
    from .dictionaries import DictionaryService

    return DictionaryService(ctx).handle(name, tx, actor, params, body, request_id)
