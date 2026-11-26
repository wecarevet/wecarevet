"""fetch_papers.py의 LLM 응답 파싱·복구 로직 테스트.

실행: python -m unittest discover -s tests   (또는 python tests/test_fetch_papers.py)
네트워크·API 호출 없이 돌아간다.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_papers as fp  # noqa: E402

GOOD = (
    "[핵심 결론] 결론입니다.\n"
    "[방법·수치] 방법입니다.\n"
    "[임상 적용·한계] 적용입니다."
)


class ExtractJsonTest(unittest.TestCase):
    def test_plain_json(self):
        obj = fp.extract_json('{"specialty": ["심장"], "summary_ko": "요약"}')
        self.assertEqual(obj["summary_ko"], "요약")

    def test_fenced_json(self):
        text = '```json\n{\n  "specialty": ["심장"],\n  "summary_ko": "요약"\n}\n```'
        obj = fp.extract_json(text)
        self.assertEqual(obj["specialty"], ["심장"])

    def test_fence_with_preface_and_tail(self):
        text = (
            "다음과 같이 정리했습니다.\n\n"
            '```json\n{"specialty": ["영상"], "summary_ko": "요약"}\n```\n\n'
            "필요한 부분이 있으면 알려주세요."
        )
        obj = fp.extract_json(text)
        self.assertEqual(obj["summary_ko"], "요약")

    def test_json_with_raw_newlines_inside_string(self):
        text = '{"specialty": ["심장"], "summary_ko": "[핵심 결론] 결과.\n[방법·수치] 방법."}'
        obj = fp.extract_json(text)
        self.assertIsNotNone(obj)
        self.assertIn("[방법·수치]", obj["summary_ko"])

    def test_json_with_trailing_comma(self):
        text = '{"specialty": ["심장"], "summary_ko": "요약",}'
        obj = fp.extract_json(text)
        self.assertEqual(obj["summary_ko"], "요약")

    def test_truncated_json_returns_none(self):
        text = '```json\n{\n  "specialty": ["심장"],\n  "summary_ko": "[핵심 결론] 잘린 응답'
        self.assertIsNone(fp.extract_json(text))


class ParseSummaryResponseTest(unittest.TestCase):
    def test_normal_response(self):
        text = '{"specialty": ["심장", "영상"], "summary_ko": "%s"}' % GOOD.replace("\n", "\\n")
        summary, tags = fp.parse_summary_response(text)
        self.assertEqual(summary, GOOD)
        self.assertEqual(tags, ["심장", "영상"])

    def test_truncated_response_is_salvaged_without_fence(self):
        text = (
            '```json\n{\n  "specialty": ["마취/진통"],\n'
            '  "summary_ko": "[핵심 결론] 진정 효과가 있었다.\\n'
            '[방법·수치] 개 53마리, Z0.6-SC 4/11마리에 추가 진정.\\n'
            '[임상 적용·한계] 더 높은 용량이 필요할 수 있으'
        )
        summary, tags = fp.parse_summary_response(text)
        self.assertFalse(fp.looks_like_raw_json(summary))
        self.assertIn("[핵심 결론]", summary)
        self.assertIn("[방법·수치]", summary)
        self.assertIn("[임상 적용·한계]", summary)
        self.assertNotIn("```", summary)
        self.assertNotIn('"summary_ko"', summary)
        self.assertEqual(tags, ["마취/진통"])

    def test_fence_only_blob_is_never_returned(self):
        text = '```json\n{"specialty": ["심장"], "summary_ko": ""}\n```'
        summary, _ = fp.parse_summary_response(text)
        self.assertEqual(summary, "")

    def test_broken_json_without_summary_key_is_dropped(self):
        text = "```json\n{\n  \"specialty\": [\n```"
        summary, _ = fp.parse_summary_response(text)
        self.assertEqual(summary, "")

    def test_plain_prose_response_still_used(self):
        summary, tags = fp.parse_summary_response(GOOD)
        self.assertEqual(summary, GOOD)
        self.assertEqual(tags, [])

    def test_unknown_specialty_filtered(self):
        text = '{"specialty": ["존재하지않는태그", "심장"], "summary_ko": "요약"}'
        summary, tags = fp.parse_summary_response(text)
        self.assertEqual(summary, "요약")
        self.assertEqual(tags, ["심장"])


class RepairTest(unittest.TestCase):
    def test_repair_broken_entry(self):
        broken = (
            '```json\n{\n  "specialty": ["심장"],\n'
            '  "summary_ko": "[핵심 결론] 결론.\\n[방법·수치] 방법.\\n[임상 적용·한계] 적용'
        )
        papers = [{
            "id": "43002247", "title": "t", "abstract": "a",
            "summary_ko": broken, "specialty": ["기타"],
        }]
        fixed = fp.repair_paper_summaries(papers, verbose=False)
        self.assertEqual(fixed, 1)
        self.assertFalse(fp.looks_like_raw_json(papers[0]["summary_ko"]))
        self.assertTrue(papers[0]["summary_ko"].startswith("[핵심 결론]"))
        self.assertEqual(papers[0]["specialty"], ["심장"])

    def test_repair_leaves_clean_entry_alone(self):
        papers = [{"id": "1", "summary_ko": GOOD, "specialty": ["심장"]}]
        self.assertEqual(fp.repair_paper_summaries(papers, verbose=False), 0)
        self.assertEqual(papers[0]["summary_ko"], GOOD)


class SummarizeKoTest(unittest.TestCase):
    """API 응답을 가짜로 바꿔 summarize_ko가 원문 JSON을 저장하지 않는지 확인."""

    def _run(self, text, stop_reason="end_turn"):
        def fake_call(payload, attempts=1):
            return {"content": [{"type": "text", "text": text}], "stop_reason": stop_reason}
        old_key, old_call = fp.ANTHROPIC_API_KEY, fp.call_claude
        fp.ANTHROPIC_API_KEY = "test"
        fp.call_claude = fake_call
        try:
            return fp.summarize_ko("제목", "초록")
        finally:
            fp.ANTHROPIC_API_KEY, fp.call_claude = old_key, old_call

    def test_fenced_json_is_parsed(self):
        text = '```json\n{"specialty": ["신장/비뇨"], "summary_ko": "%s"}\n```' % GOOD.replace("\n", "\\n")
        summary, tags = self._run(text)
        self.assertEqual(summary, GOOD)
        self.assertEqual(tags, ["신장/비뇨"])

    def test_truncated_json_is_salvaged_not_stored_raw(self):
        text = ('```json\n{\n  "specialty": ["심장"],\n  "summary_ko": "[핵심 결론] 결론.\\n'
                '[방법·수치] 방법.\\n[임상 적용·한계] 잘린 부')
        summary, tags = self._run(text, stop_reason="max_tokens")
        self.assertFalse(fp.looks_like_raw_json(summary))
        self.assertIn("[핵심 결론]", summary)
        self.assertEqual(tags, ["심장"])

    def test_empty_and_broken_returns_empty_summary(self):
        summary, tags = self._run('```json\n{"specialty": ["심장"]')
        self.assertEqual(summary, "")
        self.assertTrue(tags)  # 키워드 기반 대체 태그


class AbstractTrimTest(unittest.TestCase):
    """원문 초록 저장 길이(2,000자 상한)와 문장 경계 처리."""

    def test_limit_is_2000(self):
        self.assertEqual(fp.ABSTRACT_MAX_CHARS, 2000)

    def test_short_abstract_kept_as_is(self):
        text = "Dogs with lymphoma were treated. Median survival was 660 days."
        self.assertEqual(fp.truncate_abstract(text), text)

    def test_abstract_between_500_and_2000_is_not_cut(self):
        # 예전 500자 하드컷에서 잘려 나가던 길이의 초록은 그대로 저장돼야 한다
        text = ("To evaluate outcomes in dogs, medical records were reviewed. " * 12).strip()
        self.assertGreater(len(text), 500)
        self.assertLessEqual(len(text), 2000)
        self.assertEqual(fp.truncate_abstract(text), text)

    def test_exactly_at_limit_kept(self):
        text = "A" * 1999 + "."
        self.assertEqual(len(text), 2000)
        self.assertEqual(fp.truncate_abstract(text), text)

    def test_long_abstract_cut_at_sentence_boundary(self):
        text = ("The dog was treated and improved markedly after therapy. " * 60).strip()
        self.assertGreater(len(text), 2000)
        cut = fp.truncate_abstract(text)
        self.assertLessEqual(len(cut), 2000)
        self.assertTrue(cut.endswith("."))
        self.assertTrue(text.startswith(cut))
        # 문장 중간(단어 일부)에서 끊기지 않는다
        self.assertIn(cut[-1], ".!?")

    def test_no_sentence_end_falls_back_to_word_boundary(self):
        # 문장부호가 없이 긴 한 문장이면 단어 경계에서 자르고 말줄임표를 붙인다
        text = " ".join(["word"] * 600)
        cut = fp.truncate_abstract(text)
        self.assertLessEqual(len(cut), 2000)
        self.assertTrue(cut.endswith("…"))
        self.assertFalse(cut.endswith("wor…"))
        self.assertIn(cut[:-1][-1], "d")  # 마지막 단어가 온전히 남는다

    def test_short_last_sentence_uses_sentence_boundary(self):
        # 마지막 문장이 아주 길어도 그 앞 문장들이 상한 절반을 넘으면 문장 경계에서 자른다
        text = ("Short report. " * 200) + ("x" * 3000)
        cut = fp.truncate_abstract(text)
        self.assertLessEqual(len(cut), 2000)
        self.assertTrue(cut.endswith("report."))

    def test_decimal_numbers_do_not_end_sentence(self):
        text = ("Doses of 0.5 mg/kg were given. " * 80).strip()
        cut = fp.truncate_abstract(text)
        self.assertLessEqual(len(cut), 2000)
        self.assertNotIn("0.", cut[-6:])

    def test_trim_abstracts_applies_to_every_paper(self):
        long_text = ("Sentence about the study cohort. " * 100).strip()
        papers = [
            {"id": "1", "abstract": long_text},
            {"id": "2", "abstract": "Short one."},
            {"id": "3"},
        ]
        fp.trim_abstracts(papers)
        self.assertLessEqual(len(papers[0]["abstract"]), 2000)
        self.assertGreater(len(papers[0]["abstract"]), 500)
        self.assertEqual(papers[1]["abstract"], "Short one.")
        self.assertEqual(papers[2]["abstract"], "")


class EfetchParseTest(unittest.TestCase):
    """efetch XML에서 초록·PMC ID·DOI를 꺼내는지 확인(네트워크 없음)."""

    XML = """<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation><PMID Version="1">42833272</PMID><Article>
    <ELocationID EIdType="doi" ValidYN="Y">10.9999/fallback</ELocationID>
    <Abstract>
      <AbstractText Label="OBJECTIVE">To describe outcomes in 82 dogs.</AbstractText>
      <AbstractText Label="METHODS">Records were reviewed&#xa0;between 2017 and 2025 &amp; analyzed.</AbstractText>
    </Abstract>
  </Article></MedlineCitation>
  <PubmedData><ArticleIdList>
    <ArticleId IdType="pubmed">42833272</ArticleId>
    <ArticleId IdType="pmc">PMC1234567</ArticleId>
    <ArticleId IdType="doi">10.2460/ajvr.25.11.0407</ArticleId>
  </ArticleIdList></PubmedData>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation><PMID>111</PMID><Article>
    <ELocationID EIdType="doi">10.1/eloc</ELocationID>
    <Abstract><AbstractText>Short text without ids.</AbstractText></Abstract>
  </Article></MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>"""

    def test_abstract_pmc_and_doi(self):
        parsed = fp.parse_efetch(self.XML)
        first = parsed["42833272"]
        self.assertIn("To describe outcomes in 82 dogs.", first["abstract"])
        self.assertIn("Records were reviewed", first["abstract"])
        self.assertNotIn("AbstractText", first["abstract"])
        # AbstractText 여러 섹션을 이어 붙이고 HTML 엔티티를 되돌린다
        self.assertNotIn("&#xa0;", first["abstract"])
        self.assertIn("& analyzed", first["abstract"])
        self.assertEqual(first["pmc_id"], "PMC1234567")
        self.assertEqual(first["doi"], "10.2460/ajvr.25.11.0407")

    def test_missing_pmc_is_empty_and_doi_falls_back_to_elocation(self):
        second = fp.parse_efetch(self.XML)["111"]
        self.assertEqual(second["pmc_id"], "")
        self.assertEqual(second["doi"], "10.1/eloc")

    def test_esummary_articleids(self):
        item = {"articleids": [{"idtype": "pubmed", "value": "1"},
                               {"idtype": "pmc", "value": "PMC99"},
                               {"idtype": "doi", "value": "10.5/y"}]}
        self.assertEqual(fp.esummary_pmc_id(item), "PMC99")
        self.assertEqual(fp.esummary_doi(item), "10.5/y")
        self.assertEqual(fp.esummary_pmc_id({}), "")


class BackfillTest(unittest.TestCase):
    """기존 papers.json 소급 채우기 — 초록만 늘리고 나머지는 건드리지 않는다."""

    def _paper(self, **kw):
        base = {"id": "43000001", "title": "T", "journal": "AJVR", "type": "vet",
                "date": "2026 Nov 20", "url": "https://pubmed.ncbi.nlm.nih.gov/43000001/",
                "abstract": "Old cut abstract.", "summary_ko": "[핵심 결론] 요약.", "specialty": ["심장"]}
        base.update(kw)
        return base

    def test_extends_abstract_and_keeps_summary(self):
        paper = self._paper()
        long_abs = ("The study enrolled 82 dogs with lymphoma. " * 90).strip()
        stats = fp.apply_backfill([paper], {"43000001": {"abstract": long_abs, "pmc_id": "PMC42", "doi": "10.1/z"}})
        self.assertGreater(len(paper["abstract"]), 1500)
        self.assertLessEqual(len(paper["abstract"]), 2000)
        self.assertTrue(paper["abstract"].endswith("."))
        self.assertTrue(paper["abstract"].startswith("The study enrolled 82 dogs"))
        self.assertEqual(paper["summary_ko"], "[핵심 결론] 요약.")
        self.assertEqual(paper["specialty"], ["심장"])
        self.assertEqual(paper["date"], "2026 Nov 20")
        self.assertEqual(paper["pmc_id"], "PMC42")
        self.assertEqual(paper["doi"], "10.1/z")
        self.assertEqual(stats, {"abstract": 1, "pmc": 1, "doi": 1, "missing": 0})

    def test_never_shortens_and_never_overwrites_ids(self):
        long_abs = "A" * 1200
        paper = self._paper(abstract=long_abs, pmc_id="PMC_OLD", doi="10.old/x")
        stats = fp.apply_backfill([paper], {"43000001": {"abstract": "Too short.",
                                                        "pmc_id": "PMC_NEW", "doi": "10.new/y"}})
        self.assertEqual(paper["abstract"], long_abs)
        self.assertEqual(paper["pmc_id"], "PMC_OLD")
        self.assertEqual(paper["doi"], "10.old/x")
        self.assertEqual(stats["abstract"], 0)

    def test_missing_pmid_is_counted(self):
        paper = self._paper()
        stats = fp.apply_backfill([paper], {})
        self.assertEqual(stats["missing"], 1)
        self.assertEqual(paper["abstract"], "Old cut abstract.")

    def test_merge_keeps_pmc_id_when_fresh_lacks_it(self):
        prev = [self._paper(pmc_id="PMC1", doi="10.1/a")]
        fresh = [{"id": "43000001", "title": "T2", "abstract": "new abs", "pmc_id": "", "doi": ""}]
        merged, added = fp.merge_papers(fresh, prev)
        self.assertEqual(added, 0)
        self.assertEqual(merged[0]["pmc_id"], "PMC1")
        self.assertEqual(merged[0]["doi"], "10.1/a")
        self.assertEqual(merged[0]["title"], "T2")
        self.assertEqual(merged[0]["summary_ko"], "[핵심 결론] 요약.")


class PapersJsonTest(unittest.TestCase):
    """저장된 papers.json에 원문 JSON이 남아 있지 않은지 확인(파일이 있을 때만)."""

    def test_no_raw_json_in_papers_json(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "papers.json")
        if not os.path.exists(path):
            self.skipTest("papers.json 없음")
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        broken = [p.get("id") for p in data.get("papers", []) if fp.looks_like_raw_json(p.get("summary_ko"))]
        broken += [a.get("id") for a in data.get("clinicians_brief", []) if fp.looks_like_raw_json(a.get("summary_ko"))]
        self.assertEqual(broken, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
