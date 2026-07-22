import unittest

from src.retriever import EvidenceConfig, evaluate_evidence, extract_query_terms


def source(identifier, title, text, *, rv=1, rl=1, vector=.7, lexical=5.0):
    return {"id": identifier, "documento_id": f"doc-{identifier}", "titulo": title,
            "texto": text, "url": f"https://example/{identifier}", "score": .04,
            "score_hybrid": .04, "score_vector": vector, "score_lexical": lexical,
            "rank_vector": rv, "rank_lexical": rl}


class EvidenceTests(unittest.TestCase):
    def test_function_words_do_not_reduce_positive_evidence_coverage(self):
        json_result = evaluate_evidence(
            "Quais s\u00e3o os riscos da gamifica\u00e7\u00e3o no cotidiano?",
            [source(1, "Os riscos da gamifica\u00e7\u00e3o no cotidiano",
                    "A gamifica\u00e7\u00e3o traz riscos ao cotidiano", rv=1, rl=2)],
        )
        pdf_result = evaluate_evidence(
            "Quais s\u00e3o os quatro m\u00f3dulos do curso de organiza\u00e7\u00e3o financeira da USP?",
            [source(2, "Curso de organiza\u00e7\u00e3o financeira",
                    "S\u00e3o quatro m\u00f3dulos do curso: habilidade financeira, planejamento financeiro, investimentos, cr\u00e9dito e endividamento",
                    rv=4, rl=1)],
        )
        self.assertTrue(json_result.sufficient)
        self.assertTrue(pdf_result.sufficient)

    def test_external_question_remains_rejected_after_normalization(self):
        result = evaluate_evidence(
            "Qual foi o resultado do campeonato intergal\u00e1ctico de xadrez qu\u00e2ntico da USP?",
            [source(1, "Uma Copa entre guerras e paz", "Campeonato de futebol", rv=8, rl=1)],
        )
        self.assertFalse(result.sufficient)

    def test_accepts_complex_evidence_distributed_between_title_and_body(self):
        result = evaluate_evidence(
            "quatro modulos curso organizacao financeira",
            [source(1, "Curso de organizacao financeira",
                    "quatro modulos para planejamento", rv=4, rl=1)],
        )
        self.assertTrue(result.sufficient)
        self.assertTrue(result.classified_sources[0]["evidence_distributed_strong"])

    def test_extracts_terms_accents_ia_and_removes_framing(self):
        self.assertEqual(extract_query_terms(
            "Quais pesquisas da USP tratam de Inteligência Artificial e IA?"),
            ["inteligencia", "artificial", "ia"])
        self.assertEqual(extract_query_terms(
            "Quais notícias mencionam transferência de tecnologia?"),
            ["transferencia", "tecnologia"])

    def test_classifies_direct_partial_and_weak_deterministically(self):
        question = "Quais notícias tratam de inteligência artificial?"
        sources = [source(1, "Inteligência artificial", "Pesquisa aplicada"),
                   source(2, "Tecnologia", "Uso de inteligência artificial", rv=10, rl=12),
                   source(3, "Sustentabilidade", "Meio ambiente", rv=9, rl=None, lexical=0)]
        first = evaluate_evidence(question, sources)
        second = evaluate_evidence(question, sources)
        self.assertEqual([x["evidence_class"] for x in first.classified_sources],
                         ["direct", "partial", "weak"])
        self.assertEqual(first.decision, second.decision)
        self.assertEqual(first.metrics["query_term_coverage"], 1.0)

    def test_accepts_two_complementary_relevant_sources(self):
        result = evaluate_evidence("inteligência artificial", [
            source(1, "Inteligência artificial", "Aplicação"),
            source(2, "Tecnologia", "inteligência artificial aplicada", rv=8, rl=6)])
        self.assertTrue(result.sufficient)

    def test_accepts_single_strong_title_source(self):
        result = evaluate_evidence("transferência tecnologia", [
            source(1, "Transferência de tecnologia", "Agência de inovação")])
        self.assertTrue(result.sufficient)

    def test_accepts_single_strong_partial_with_high_coverage(self):
        result = evaluate_evidence("bolsa familia reduziu hospitalizacoes empregabilidade", [
            source(1, "Bolsa Familia reduziu hospitalizacoes",
                   "Resultados sociais", rv=1, rl=1)])
        self.assertTrue(result.sufficient)
        self.assertTrue(result.classified_sources[0]["evidence_strong_partial"])
        self.assertEqual([item["id"] for item in result.context_sources], [1])

    def test_rejects_weak_partial_with_low_lexical_rank(self):
        result = evaluate_evidence("bolsa familia reduziu hospitalizacoes empregabilidade", [
            source(1, "Bolsa Familia reduziu hospitalizacoes",
                   "Resultados sociais", rv=2, rl=8)])
        self.assertFalse(result.sufficient)
        self.assertFalse(result.classified_sources[0]["evidence_strong_partial"])

    def test_accepts_nearly_identical_title(self):
        result = evaluate_evidence(
            "O que diz a noticia Bolsa Familia reduziu hospitalizacoes e aumentou empregabilidade?",
            [source(1, "Bolsa Familia reduziu hospitalizacoes e aumentou empregabilidade, aponta estudo",
                    "Resultados do levantamento", rv=1, rl=1)],
        )
        self.assertTrue(result.sufficient)

    def test_accepts_strong_content_match_with_hybrid_signals(self):
        result = evaluate_evidence("acao climatica saude ambiental pesquisa", [
            source(1, "Semana de debates", "acao climatica e saude ambiental em debate", rv=1, rl=1)])
        self.assertTrue(result.sufficient)
        self.assertTrue(result.classified_sources[0]["evidence_strong_partial"])

    def test_single_term_query_remains_conservative(self):
        result = evaluate_evidence("tecnologia", [
            source(1, "Tecnologia", "Tecnologia aplicada", rv=1, rl=1)])
        self.assertFalse(result.sufficient)

    def test_superficial_technology_match_is_rejected(self):
        result = evaluate_evidence("transferencia tecnologia", [
            source(1, "Transferencia financeira", "Uso de tecnologia bancaria", rv=1, rl=1)])
        self.assertFalse(result.sufficient)
        self.assertFalse(result.classified_sources[0]["evidence_strong_partial"])

    def test_accepts_single_strong_body_source_without_title_match(self):
        result = evaluate_evidence("transferência tecnologia", [
            source(1, "Agência de inovação", "transferência de tecnologia")])
        self.assertTrue(result.sufficient)
        self.assertEqual([x["id"] for x in result.context_sources], [1])

    def test_rejects_five_weak_and_removes_them(self):
        weak = [source(i, "Assunto distante", "sem correspondência", rv=10+i,
                       rl=None, lexical=0) for i in range(1, 6)]
        result = evaluate_evidence("transferência tecnologia", weak)
        self.assertFalse(result.sufficient)
        self.assertEqual(result.refusal_reason, "all_sources_weak")
        self.assertEqual(result.public_sources, [])
        self.assertTrue(result.metrics["ollama_skipped"])

    def test_vector_semantic_partial_without_lexical_is_not_enough_alone(self):
        item = source(1, "Modelos inteligentes", "inteligência aplicada",
                      rv=1, rl=None, lexical=0)
        result = evaluate_evidence("inteligência artificial", [item])
        self.assertFalse(result.sufficient)
        self.assertEqual(result.classified_sources[0]["evidence_class"], "partial")

    def test_disabled_check_preserves_all_sources(self):
        items = [source(1, "Outro tema", "sem relação", rl=None, lexical=0)]
        result = evaluate_evidence("inteligência artificial", items,
                                   EvidenceConfig(enabled=False))
        self.assertTrue(result.sufficient)
        self.assertEqual(result.context_sources, items)
        self.assertEqual(result.refusal_reason, "evidence_check_disabled")


if __name__ == "__main__":
    unittest.main()
