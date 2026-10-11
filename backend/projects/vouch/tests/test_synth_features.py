from collections import Counter

from vouch.dataset import build_rows
from vouch.domain import RiskClass
from vouch.features import NUMERIC_FEATURES
from vouch.graph_features import VendorGraph
from vouch.identity import address_is_virtual, make_tax_id, phone_is_voip, tax_id_valid
from vouch.scorer import HeuristicScorer
from vouch.synth import generate_world


def test_world_is_seeded_and_covers_every_class():
    a, b = generate_world(seed=3, n_vendors=300), generate_world(seed=3, n_vendors=300)
    assert [i.model_dump() for i in a.invoices] == [i.model_dump() for i in b.invoices]
    classes = Counter(lbl.risk_class for lbl in a.labels.values())
    assert set(classes) == set(RiskClass)
    assert any(lbl.honest_unusual for lbl in a.labels.values())
    patterns = {lbl.pattern for lbl in a.labels.values()}
    assert {
        "duplicate",
        "split",
        "creep",
        "fake_vendor",
        "honest_new_small",
        "honest_bank_change_ok",
    } <= patterns
    assert all(isinstance(i.amount_cents, int) and i.amount_cents > 0 for i in a.invoices)


def test_identity_checks():
    assert tax_id_valid(make_tax_id("12345678"))
    assert not tax_id_valid("12-3456780") or not tax_id_valid("12-3456781")
    assert phone_is_voip("+1-888-555-0123") and not phone_is_voip("+1-816-555-0100")
    assert address_is_virtual("PO Box 12, Omaha") and not address_is_virtual("12 Main St")


def test_rings_show_up_in_the_vendor_graph(service):
    g = service.graph
    shared = g.shared("v-apex")
    assert set(shared["bank"]) == {"v-summit", "v-northgate"}
    feats = g.features("v-apex")
    assert feats["shared_bank"] == 2 and feats["component_size"] >= 3 and feats["neighbour_suspicion"] > 0.5
    assert g.shared("v-prairie") == {}


def test_features_and_heuristic_scorer_separate_classes():
    world = generate_world(seed=5, n_vendors=400)
    rows = build_rows(world, graph=VendorGraph.build(world.vendors))
    assert all(set(r.numeric) == set(NUMERIC_FEATURES) for r in rows)
    scores = HeuristicScorer().score([{"features": r.numeric} for r in rows], explain=False)
    honest = [
        s.legitimacy for s, r in zip(scores, rows, strict=True) if r.label.risk_class == RiskClass.HONEST
    ]
    bad = [s.legitimacy for s, r in zip(scores, rows, strict=True) if r.label.risk_class != RiskClass.HONEST]
    assert sum(honest) / len(honest) > sum(bad) / len(bad) + 0.2
