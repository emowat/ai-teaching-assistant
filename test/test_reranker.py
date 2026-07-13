import pytest
import math
from rag.reranker import _jaccard_sim, mmr_diversify, apply_category_weights
from rag.schemas import RetrievedDoc, DocCategory, SourceDomain

def test_jaccard_sim():
    # Identical sets
    assert _jaccard_sim({"a", "b"}, {"a", "b"}) == 1.0
    
    # Completely disjoint sets
    assert _jaccard_sim({"a", "b"}, {"c", "d"}) == 0.0
    
    # Partial overlap (a,b vs b,c -> intersection 1, union 3)
    assert math.isclose(_jaccard_sim({"a", "b"}, {"b", "c"}), 1.0 / 3.0)
    
    # Empty sets
    assert _jaccard_sim(set(), {"a"}) == 0.0
    assert _jaccard_sim({"a"}, set()) == 0.0
    assert _jaccard_sim(set(), set()) == 0.0

def test_mmr_diversify_relevance_only():
    """If lambda_param is 1.0, MMR should just return the top K documents by relevance, ignoring diversity."""
    docs = [
        RetrievedDoc(chunk_id="1", content="identical content", category=DocCategory.SUPPLEMENTARY, week=1, priority=1, score=0.9, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
        RetrievedDoc(chunk_id="2", content="identical content", category=DocCategory.SUPPLEMENTARY, week=1, priority=1, score=0.8, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
        RetrievedDoc(chunk_id="3", content="identical content", category=DocCategory.SUPPLEMENTARY, week=1, priority=1, score=0.7, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
    ]
    
    # lambda_param=1.0 means we only care about relevance (doc.score)
    selected = mmr_diversify(docs, lambda_param=1.0, final_k=2)
    assert len(selected) == 2
    assert selected[0].chunk_id == "1"
    assert selected[1].chunk_id == "2"

def test_mmr_diversify_with_diversity():
    """If lambda_param is 0.5, MMR should penalize documents that are too similar to already selected ones."""
    docs = [
        RetrievedDoc(chunk_id="1", content="dog cat bird", category=DocCategory.SUPPLEMENTARY, week=1, priority=1, score=0.9, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
        RetrievedDoc(chunk_id="2", content="dog cat bird", category=DocCategory.SUPPLEMENTARY, week=1, priority=1, score=0.85, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
        RetrievedDoc(chunk_id="3", content="apple banana orange", category=DocCategory.SUPPLEMENTARY, week=1, priority=1, score=0.8, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
    ]
    
    # Doc 2 is very similar to Doc 1 (Jaccard = 1.0). 
    # With a lambda < 1.0, the penalty for similarity should push Doc 3 ahead of Doc 2.
    selected = mmr_diversify(docs, lambda_param=0.5, final_k=2)
    assert len(selected) == 2
    assert selected[0].chunk_id == "1"
    assert selected[1].chunk_id == "3"  # Doc 3 is chosen over Doc 2 due to diversity

def test_apply_category_weights():
    docs = [
        RetrievedDoc(chunk_id="1", content="", category=DocCategory.SUPPLEMENTARY, week=1, priority=1, score=1.0, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
        RetrievedDoc(chunk_id="2", content="", category=DocCategory.STRICT_RULES, week=1, priority=1, score=1.0, source_domain=SourceDomain.MIT_OCW_LECTURE, source_type=""),
    ]
    
    weights = {
        DocCategory.SUPPLEMENTARY: 1.0,
        DocCategory.STRICT_RULES: 2.0,
    }
    
    weighted_docs = apply_category_weights(docs, weights)
    
    # Since Strict Rules has a higher weight, Doc 2 should be boosted to the top and have a score of 2.0
    assert weighted_docs[0].chunk_id == "2"
    assert weighted_docs[0].score == 2.0
    assert weighted_docs[1].chunk_id == "1"
    assert weighted_docs[1].score == 1.0
