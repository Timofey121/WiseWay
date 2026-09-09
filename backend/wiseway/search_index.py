"""Derived token postings for one immutable, published metadata generation."""

from bisect import bisect_left
from collections import defaultdict
from heapq import nlargest, nsmallest
from threading import Lock

from .common import ApiError
from .search import _contains_phrase, _facet_from_groups, _field_streams, _natural_key, _path_tie, _sort_rows


class SearchIndex:
    def __init__(self, items):
        self.items = items
        self._chains = defaultdict(list)
        self._postings = defaultdict(dict)
        self._fields = []
        self._facets = defaultdict(dict)
        self._order_lock = Lock()
        self._path_ranks = None
        self._name_ranks = None
        for position, item in enumerate(items):
            chain = []
            self._chains[()].append(position)
            for marker in item["markers"]:
                grouped = self._facets[tuple(chain)]
                known, count = grouped.get(marker["marker_id"], (marker, 0))
                grouped[marker["marker_id"]] = (known, count + 1)
                chain.append(marker["marker_id"])
                self._chains[tuple(chain)].append(position)
            fields = _field_streams(item)
            self._fields.append(fields)
            for weight, tokens in fields:
                for token in tokens:
                    postings = self._postings[token]
                    postings[position] = max(weight, postings.get(position, 0))
        self._vocabulary = sorted(self._postings)

    def _positions(self, selected):
        if len(selected) != len(set(selected)):
            raise ApiError("INVALID_MARKER_SELECTION", "Цепочка содержит повторный маркер", 422)
        positions = self._chains.get(tuple(selected), [])
        if selected and not positions:
            raise ApiError("INVALID_MARKER_SELECTION", "Недопустимая цепочка маркеров", 422)
        return positions

    def selected(self, selected):
        return [self.items[position] for position in self._positions(selected)]

    def selected_markers(self, selected):
        positions = self._positions(selected)
        return self.items[positions[0]]["markers"][: len(selected)] if selected else []

    def next_facet(self, selected, prefix):
        self._positions(selected)
        return _facet_from_groups(self._facets.get(tuple(selected), {}), prefix)

    def _term_postings(self, term):
        result = []
        start = bisect_left(self._vocabulary, term)
        for offset in range(start, len(self._vocabulary)):
            token = self._vocabulary[offset]
            if not token.startswith(term):
                break
            result.append((2 if token == term else 1, self._postings[token]))
        return result

    def match(self, query, selected):
        positions = self._positions(selected)

        def allowed(position):
            if not selected:
                return True
            offset = bisect_left(positions, position)
            return offset < len(positions) and positions[offset] == position

        scores = None
        terms = sorted(
            (self._term_postings(term) for (term,) in query.terms),
            key=lambda matches: sum(len(postings) for _, postings in matches),
        )
        for matches in terms:
            matched = {}
            for multiplier, postings in matches:
                candidates = scores if scores is not None and len(scores) < len(postings) else postings
                for position in candidates:
                    weight = postings.get(position)
                    if weight is not None and (
                        position in scores if scores is not None else allowed(position)
                    ):
                        matched[position] = max(weight * multiplier, matched.get(position, 0))
            scores = {
                position: (scores[position] if scores is not None else 0) + score
                for position, score in matched.items()
            }
            if not scores:
                return []
        for phrase in query.phrases:
            matched = {}
            smallest = min((self._postings.get(token, {}) for token in phrase), key=len)
            candidates = scores if scores is not None and len(scores) < len(smallest) else smallest
            for position in candidates:
                if position not in smallest or (
                    position not in scores if scores is not None else not allowed(position)
                ):
                    continue
                weights = [
                    weight for weight, tokens in self._fields[position] if _contains_phrase(tokens, phrase)
                ]
                if weights:
                    matched[position] = (scores[position] if scores is not None else 0) + (
                        2 * len(phrase) * max(weights)
                    )
            scores = matched
            if not scores:
                return []
        # Preserve corpus order until the public ranking/tie-breaker sort.
        if scores is None:
            return [(self.items[position], 0) for position in positions]
        return [(self.items[position], scores[position]) for position in sorted(scores)]

    def sort_rows(self, rows, ordering, limit):
        if len(rows) <= limit:
            return _sort_rows(rows, ordering)
        # Reuse only ordinal ranks, not expanded natural-key tuples for every
        # response. They belong to this immutable generation and stay bounded
        # by its item count. Small selective queries need neither rank cache.
        _sort_rows([], ordering)
        field = ordering["field"]
        with self._order_lock:
            if self._path_ranks is None:
                self._path_ranks = {
                    id(row): rank for rank, row in enumerate(sorted(self.items, key=_path_tie))
                }
            if field == "NAME" and self._name_ranks is None:
                ranks, previous, rank = {}, None, -1
                for row in sorted(self.items, key=lambda row: _natural_key(row["filename"])):
                    key = _natural_key(row["filename"])
                    if key != previous:
                        rank += 1
                    ranks[id(row)], previous = rank, key
                self._name_ranks = ranks
        path_ranks = self._path_ranks
        descending = ordering["direction"] == "DESC"

        def key(pair):
            row, score = pair
            path_rank = path_ranks[id(row)]
            if field == "PATH":
                return path_rank
            if field == "RELEVANCE":
                primary = score
            elif field == "NAME":
                primary = self._name_ranks[id(row)]
            else:
                primary = row["size_bytes" if field == "SIZE" else "modified_at"]
            return primary, -path_rank if descending else path_rank

        select = nlargest if descending else nsmallest
        return [row for row, _ in select(limit, rows, key=key)]
