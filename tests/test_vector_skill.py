from pathlib import Path

S = "skills/vector-rag-dev"


def test_skill_exists(repo_root: Path):
    assert (repo_root / S / "SKILL.md").is_file()


def test_vector_search_states_ivf_default_and_hnsw_memory(repo_root: Path):
    v = (repo_root / S / "references/vector-search.md").read_text().lower()
    assert "ivf" in v
    assert "hnsw" in v and "vector_memory_size" in v


def test_rag_pipeline_offline_first(repo_root: Path):
    r = (repo_root / S / "references/rag-pipeline.md").read_text().lower()
    assert "dbms_vector_chain" in r
    assert "onnx" in r or "ollama" in r


def test_modeling_calibrations_cover_the_four_field_lessons(repo_root: Path):
    m = (repo_root / S / "references/modeling-calibrations.md").read_text().lower()
    # freshness vs recall drift are distinct decay modes
    assert "freshness" in m and "recall drift" in m
    # filtered ANN prunes inside index selection, not after top-k
    assert "post-filter" in m or "index selection" in m
    # hybrid-index accuracy numbers ship WITH internal-benchmark framing
    assert "68%" in m and "94%" in m and "internal" in m
    # split calibration: converged default, no speed-crown claims
    assert "billion-scale" in m and "speed crown" in m
    # pointer back to the modeling skill's guardrails
    assert "claims-guardrails.md" in m


def test_skill_links_modeling_calibrations(repo_root: Path):
    s = (repo_root / S / "SKILL.md").read_text().lower()
    assert "modeling-calibrations.md" in s
