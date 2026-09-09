"""Derived token postings for one immutable, published metadata generation."""

from bisect import bisect_left
from collections import defaultdict

from .common import ApiError
from .search import _contains_phrase, _field_streams


class SearchIndex:
    def __init__(self, items):
        self.items = items
        self._chains = defaultdict(list)
        self._postings = defaultdict(dict)
        self._fields = []
        for position, item in enumerate(items):
            chain = []
            self._chains[()].append(position)
            for marker in item["markers"]:
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

    def match(self, query, selected):
        scores = dict.fromkeys(self._positions(selected), 0)
        for (term,) in query.terms:
            matched = {}
            start = bisect_left(self._vocabulary, term)
            for offset in range(start, len(self._vocabulary)):
                token = self._vocabulary[offset]
                if not token.startswith(term):
                    break
                multiplier = 2 if token == term else 1
                for position, weight in self._postings[token].items():
                    if position in scores:
                        matched[position] = max(weight * multiplier, matched.get(position, 0))
            scores = {position: scores[position] + score for position, score in matched.items()}
            if not scores:
                return []
        for phrase in query.phrases:
            matched = {}
            first_token = self._postings.get(phrase[0], {})
            for position, score in scores.items():
                if position not in first_token:
                    continue
                weights = [
                    weight for weight, tokens in self._fields[position] if _contains_phrase(tokens, phrase)
                ]
                if weights:
                    matched[position] = score + 2 * len(phrase) * max(weights)
            scores = matched
            if not scores:
                return []
        # Preserve corpus order until the public ranking/tie-breaker sort.
        return [(self.items[position], scores[position]) for position in sorted(scores)]
