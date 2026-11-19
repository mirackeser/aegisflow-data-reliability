# SPDX-License-Identifier: Apache-2.0
"""Does passage-level retrieval beat whole-document retrieval on long documents? A synthetic, seeded comparison.

Twelve documents of eight paragraphs are generated from six topic vocabularies (two documents share each topic, so
documents compete), with shared filler words and a few words from other topics as noise. Each of the 96 queries
uses words that occur only in one paragraph of its document, so the answer passage is well defined. The corpus is
synthetic word lists, not real prose: it shows what chunking changes mechanically (size of the cited context, exact
span, finding the right passage) and says nothing about real documents or about meaning.
"""
from __future__ import annotations

from random import Random

from aegisflow_dr.check_evaluation import wilson
from knowledge import Document, Knowledge, terms

DOMAINS = {
    "finance": "invoice ledger payment refund balance credit debit audit tax budget payroll revenue margin forecast deposit interest loan asset liability equity dividend currency account receipt voucher penalty discount surcharge settlement escrow tariff premium royalty overdraft collateral remittance",
    "logistics": "shipment pallet freight carrier depot warehouse courier customs dispatch routing container cargo parcel tracking pickup delivery transit manifest haulage dock forklift inventory shelving barcode backorder fleet driver mileage fuel tonnage consignment stowage quay lorry stevedore",
    "people": "recruit appraisal mentor vacancy contract probation overtime holiday leave benefits pension resignation dismissal grievance training promotion seniority shift rota timesheet orientation referral hiring interview headcount succession diversity wellbeing sabbatical apprenticeship tenure stipend secondment",
    "security": "firewall password token encryption certificate breach malware phishing patch vulnerability intrusion authentication authorization session cookie keystore hashing signature sandbox quarantine exploit botnet ransomware spoofing credential privilege backdoor honeypot checksum cipher handshake nonce revocation whitelist blacklist forensics rootkit",
    "product": "roadmap feature backlog sprint release prototype usability wireframe persona feedback pricing bundle launch beta changelog deprecation integration plugin dashboard widget template localization accessibility benchmark telemetry experiment cohort retention funnel churn mockup stakeholder milestone",
    "support": "ticket escalation queue helpdesk chatbot callback resolution satisfaction warranty replacement complaint triage knowledge macro transcript voicemail apology workaround outage incident hotline survey agent greeting handover backlog-free reopen priority severity sla ownership followup",
}
SHARED = "process report team review update policy request system service customer manager record schedule approval document standard guideline owner status change".split()
PREFIXES = ("net", "pre", "sub", "re", "co", "multi", "inter", "auto")  # widen each topic vocabulary to about 300 distinct words
DOCUMENTS, SECTIONS, SEED = 12, 8, 2026


def corpus(seed: int = SEED):
    rng = Random(seed)
    names = sorted(DOMAINS)
    vocab = {name: [w for base in DOMAINS[name].split() for w in (base, *(p + base for p in PREFIXES))] for name in names}
    documents, gold = [], []
    for number in range(DOCUMENTS):
        topic = names[number % len(names)]
        other = [w for n in names if n != topic for w in vocab[n]]
        paragraphs, sections = [], []
        for _ in range(SECTIONS):
            words = rng.sample(vocab[topic], 14) + rng.sample(SHARED, 8) + rng.sample(other, 2)
            rng.shuffle(words)
            paragraphs.append(" ".join(f"{' '.join(words[i:i + 12]).capitalize()}." for i in range(0, 24, 12)))
            sections.append(set(words) & set(vocab[topic]))
        text = "\n\n".join(paragraphs)
        documents.append(Document("local", f"synthetic-{number:02d}", "v1", text))
        offsets = [text.index(p) for p in paragraphs]
        for index, (offset, paragraph) in enumerate(zip(offsets, paragraphs)):
            unique = sorted(sections[index] - set().union(*(sections[j] for j in range(SECTIONS) if j != index)))
            if len(unique) >= 4:
                gold.append({"source": f"synthetic-{number:02d}", "section": index, "offset": offset, "unique": unique})
    return tuple(documents), gold


def _rate(successes: int, trials: int) -> dict:
    return {"value": round(successes / trials, 4), "numerator": successes, "denominator": trials, "wilson95": wilson(successes, trials)}


def _measure(knowledge, allowed, gold, queries) -> dict:
    doc_hits = pass_doc_hits = pass_hits = doc_bytes = pass_bytes = 0
    for item, query in zip(gold, queries):
        top_doc = knowledge.retrieve("local", query, allowed_sources=allowed, limit=1)
        top_pass = knowledge.retrieve_passages("local", query, allowed_sources=allowed, limit=1)
        if top_doc:
            doc_hits += top_doc[0]["source"] == item["source"]
            doc_bytes += len(top_doc[0]["text"].encode("utf-8"))
        if top_pass:
            first = top_pass[0]
            pass_doc_hits += first["source"] == item["source"]
            pass_hits += first["source"] == item["source"] and first["start"] <= item["offset"] < first["end"]
            pass_bytes += len(first["text"].encode("utf-8"))
    n = len(gold)
    return {"queries": n, "document_level": {"right_document_first": _rate(doc_hits, n), "mean_returned_bytes": round(doc_bytes / n)},
            "passage_level": {"right_document_first": _rate(pass_doc_hits, n), "right_passage_first": _rate(pass_hits, n),
                              "mean_returned_bytes": round(pass_bytes / n)}}


def evaluate() -> dict:
    documents, gold = corpus()
    knowledge = Knowledge()
    knowledge.replace(documents)
    allowed = frozenset(d.source for d in documents)
    groups = {}
    for words in (4, 2):
        rng = Random(SEED + words)
        queries = [" ".join(rng.sample(item["unique"], words)) for item in gold]
        groups[f"{words}_distinctive_words"] = _measure(knowledge, allowed, gold, queries)
    mean_document = sum(len(d.text.encode("utf-8")) for d in documents) / len(documents)
    return {"documents": len(documents), "queries_per_group": len(gold), "synthetic": True,
            "mean_document_bytes": round(mean_document), "groups": groups}


def _pct(rate: dict) -> str:
    low, high = rate["wilson95"]
    return f"{rate['numerator']}/{rate['denominator']} ({rate['value']:.0%}, 95% interval {low:.0%}–{high:.0%})"


def render_markdown(report: dict) -> str:
    lines = ["# Passage retrieval evaluation", "",
             f"Synthetic and seeded: {report['documents']} generated documents of about {report['mean_document_bytes']} bytes (eight paragraphs each, "
             f"two documents per topic) and {report['queries_per_group']} queries per group. The text is generated word lists, not real prose, "
             "so this shows what splitting into passages changes mechanically and says nothing about real documents, meaning or generated answers. "
             "Each query uses words that occur in only one paragraph of its document.", "",
             "| Query | Method | Right document first | Right passage first | Mean returned bytes |", "|---|---|---|---|---|"]
    for name, group in report["groups"].items():
        label = name.replace("_", " ")
        document, passage = group["document_level"], group["passage_level"]
        lines.append(f"| {label} | whole document | {_pct(document['right_document_first'])} | not applicable | {document['mean_returned_bytes']} |")
        lines.append(f"| {label} | passage | {_pct(passage['right_document_first'])} | {_pct(passage['right_passage_first'])} | {passage['mean_returned_bytes']} |")
    lines += ["", "Reading the numbers: with four distinctive words both methods find the right document every time, so the gain is the cited context, "
              "which is about eight times smaller and comes with its exact character span and its own verifiable citation. With only two distinctive "
              "words the passage method found the right document slightly more often, but the difference is a few queries and the intervals overlap, "
              "so it is not shown to be better. Questions whose evidence is spread over several paragraphs are answered only in part by one passage.", ""]
    return "\n".join(lines)


def main() -> None:  # pragma: no cover - thin CLI
    import sys
    import json
    print(render_markdown(evaluate()) if "--markdown" in sys.argv else json.dumps(evaluate(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
