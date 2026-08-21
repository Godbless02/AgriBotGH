# AgriBotGH Final Project Report Data

Generated from saved evaluation artifacts. Values below are measured, not estimated.

## Dataset and split

- Canonical bilingual records: **563**
- English Q&A pairs: **563**
- Twi Q&A pairs: **563**
- Categories: **40**
- Training / validation / testing: **394 / 84 / 85**

## Final model

- Version: **AgriBotGH Retrieval Model v1.0.1**
- Architecture: **topic-aware word + character TF-IDF**
- Weights: **TF-IDF 0.38, topic 0.62, embedding 0.00**
- Confidence signal: **normalized candidate-score margin**
- Confidence threshold: **0.27**

## Validation retrieval metrics

| Language | Top-1 | Top-3 | Precision | Ranking coverage | Category match |
|---|---:|---:|---:|---:|---:|
| English | 50.00% | 66.67% | 10.71% | 100.00% | 47.62% |
| Twi | 50.00% | 61.11% | 10.71% | 100.00% | 53.57% |

At threshold 0.27, automatic-answer response precision was **100.00%** and response coverage was **0.60%**. This conservative threshold produced no observed false-positive automatic answers in validation.

## Independent behavior evidence

- Off-topic challenge: **48/48**
- Agricultural edge cases: **32/32**
- Language-separation cases: **80/80**
- Final presentation cases: **80/80**
- High-risk safety-notice coverage: **100%** of detected high-risk canonical answers

## Performance

- Cold startup: **9.540 seconds**
- Retrieval latency: **13.827 ms average**, **20.372 ms p95**
- Flask test-client latency: **12.027 ms average**, **27.819 ms p95**
- Working-set memory: **167.81 MB**

## Reporting cautions

- Retrieval coverage is not automatic-answer coverage.
- Similarity and score margin are not calibrated probabilities.
- No human participant usability results were supplied.
- Automated checks cannot establish agronomic correctness or native Twi naturalness; qualified review remains future work.
