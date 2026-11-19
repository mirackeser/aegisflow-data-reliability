# Passage retrieval evaluation

Synthetic and seeded: 12 generated documents of about 2018 bytes (eight paragraphs each, two documents per topic) and 96 queries per group. The text is generated word lists, not real prose, so this shows what splitting into passages changes mechanically and says nothing about real documents, meaning or generated answers. Each query uses words that occur in only one paragraph of its document.

| Query | Method | Right document first | Right passage first | Mean returned bytes |
|---|---|---|---|---|
| 4 distinctive words | whole document | 96/96 (100%, 95% interval 96%–100%) | not applicable | 2018 |
| 4 distinctive words | passage | 96/96 (100%, 95% interval 96%–100%) | 96/96 (100%, 95% interval 96%–100%) | 250 |
| 2 distinctive words | whole document | 90/96 (94%, 95% interval 87%–97%) | not applicable | 2018 |
| 2 distinctive words | passage | 94/96 (98%, 95% interval 93%–99%) | 94/96 (98%, 95% interval 93%–99%) | 250 |

Reading the numbers: with four distinctive words both methods find the right document every time, so the gain is the cited context, which is about eight times smaller and comes with its exact character span and its own verifiable citation. With only two distinctive words the passage method found the right document slightly more often, but the difference is a few queries and the intervals overlap, so it is not shown to be better. Questions whose evidence is spread over several paragraphs are answered only in part by one passage.

