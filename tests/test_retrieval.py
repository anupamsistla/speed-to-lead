from leadagent.retrieval import BM25Retriever
from leadagent.retrieval.bm25 import chunk_markdown, tokenize


def make(bundle):
    r = BM25Retriever()
    r.index(bundle.knowledge)
    return r


def test_every_hit_carries_its_source_file(bundle):
    hits = make(bundle).search("how long does the consultation take", k=5)
    assert hits
    sources = {d.source for d in bundle.knowledge}
    assert all(h.source in sources for h in hits)


def test_finds_the_right_document(bundle):
    r = make(bundle)
    assert r.search("how long is the workmanship warranty")[0].source == "knowledge/warranty.md"
    assert r.search("do you offer loans or a lease")[0].source == "knowledge/financing.md"
    assert r.search("can I add a battery")[0].source in {
        "knowledge/faq.md",
        "knowledge/services.md",
    }


def test_unrelated_question_returns_nothing(bundle):
    r = make(bundle)
    assert r.search("do you do pool heating or hot tubs") == []
    assert r.search("what is the weather") == []
    assert r.search("") == []


def test_chunking_keeps_headings():
    from leadagent.config.schemas import KnowledgeDoc

    chunks = chunk_markdown(
        KnowledgeDoc(source="knowledge/x.md", text="# T\n\n## A\nalpha\n\n## B\nbeta\n")
    )
    assert chunks == [("A", "alpha"), ("B", "beta")]


def test_tokenize_drops_stopwords_and_plurals():
    assert tokenize("What are the panels, roofs and glass?") == ["panel", "roof", "glass"]


def test_one_shared_word_is_not_an_answer(bundle):
    r = make(bundle)
    # "install" appears in the docs, but the question is about something else
    assert r.search("do you install pool heaters") == []
    assert r.search("how much does it cost for a 2000 sq ft house") == []
