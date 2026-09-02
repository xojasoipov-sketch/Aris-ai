"""memory/scoring.py testlari — kalit-so'z, vektor va hybrid balllar."""

from __future__ import annotations

from zet.memory.scoring import cosine_similarity, hybrid_score, keyword_score


class TestKeywordScore:
    def test_exact_substring_match(self) -> None:
        assert keyword_score("Python", "Python dasturlash tili") == 0.8

    def test_summary_match_lower_than_content(self) -> None:
        assert keyword_score("Python", "boshqa matn", summary="Python haqida") == 0.75

    def test_word_overlap_partial(self) -> None:
        score = keyword_score("tez samarali kod", "kod samarali bo'lishi kerak")
        assert 0.0 < score < 0.8

    def test_no_match_returns_zero(self) -> None:
        assert keyword_score("mutlaqo aloqasiz", "boshqa mavzu") == 0.0

    def test_empty_query(self) -> None:
        assert keyword_score("", "matn") == 0.8  # bo'sh string har qanday matnda "topiladi"


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_opposite_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0

    def test_empty_vectors(self) -> None:
        assert cosine_similarity([], []) == 0.0

    def test_mismatched_length(self) -> None:
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_norm(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestHybridScore:
    def test_no_vector_falls_back_to_keyword(self) -> None:
        assert hybrid_score(keyword=0.6, vector=None) == 0.6

    def test_blends_keyword_and_vector(self) -> None:
        result = hybrid_score(keyword=0.5, vector=0.9)
        # 0.4*0.5 + 0.6*0.9 = 0.74
        assert abs(result - 0.74) < 1e-6

    def test_negative_vector_clamped_to_zero(self) -> None:
        result = hybrid_score(keyword=0.5, vector=-0.8)
        assert result == 0.4 * 0.5  # vektor hissasi 0 ga tushadi

    def test_result_capped_at_one(self) -> None:
        assert hybrid_score(keyword=1.0, vector=1.0) <= 1.0

    def test_zero_keyword_high_vector_still_scores(self) -> None:
        """Semantik jihatdan mos, lekin so'zma-so'z mos kelmaydigan holat."""
        result = hybrid_score(keyword=0.0, vector=0.95)
        assert result > 0.5
