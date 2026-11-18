# Reference retrieval evaluation

Method: lexical term overlap over 6 built-in reference documents and 32 labelled queries. The queries were written with the documents in view, so this is a regression guard and a picture of lexical matching, not an independent benchmark. It measures retrieval only; no model is involved and nothing here says anything about generated answers.

| Group | Queries | Right document first | Right document in top 3 | Mean reciprocal rank |
|---|---|---|---|---|
| keyword | 18 | 18/18 (100%, 95% interval 82%–100%) | 18/18 (100%, 95% interval 82%–100%) | 1.0000 |
| paraphrase | 8 | 3/8 (38%, 95% interval 14%–69%) | 4/8 (50%, 95% interval 22%–78%) | 0.4375 |

Out of scope (6 queries with no relevant document): nothing returned for 6/6 (100%, 95% interval 61%–100%); a result was wrongly returned for 0/6 (0%, 95% interval 0%–39%).

Reading the numbers: keyword queries reuse document wording, so matching is easy. Paraphrase queries are the realistic case and show the limit of matching on shared words. Intervals are wide because the samples are small.

History: the first measurement returned a result for 67% of out-of-scope queries because function words such as `the` and `is` counted as evidence. Removing them brought that to 0% and moved paraphrase right-first from 25% to 38%.

