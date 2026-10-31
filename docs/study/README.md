# Study Notes

Teaching notes on the loan limit model: each technique explained from first principles, with worked numbers, weaknesses and self-test questions. Read the [research report](../report.md) first for the problem and the results; these notes explain how and why it works.

Numbers marked "real" come from the research run on a 30,000-customer 2023 book. The code in this repository reproduces the method on synthetic data, so its own outputs differ.

## Start here

| # | Note | What it covers |
|---|---|---|
| 01 | [The model step by step](01-the-model-step-by-step.md) | The whole project in nine steps, from the business question to the results, with toy examples |
| 02 | [How the pieces connect](02-how-the-pieces-connect.md) | What feeds what: inputs, the MDP, the λ loop, the simulator and the stress tests, with diagrams |

## Part 1. The data

| # | Note | What it covers |
|---|---|---|
| 03 | [Can uptake be predicted?](03-can-uptake-be-predicted.md) | Logistic regression, LightGBM, AUC, cross-validation and a permutation test: why no feature-based uptake model was built |
| 04 | [Reading the decile charts](04-reading-the-decile-charts.md) | How to read three flat lines, and the business finding behind them: 2023 increases ignored risk |
| 05 | [The profit column puzzle](05-the-profit-column-puzzle.md) | Why the data's profit is 40 × (n − 2), two rules that fit it equally well, and what that means for the model |

## Part 2. The method

| # | Note | What it covers |
|---|---|---|
| 06 | [Risk buckets and Bayesian updating](06-risk-buckets-and-bayesian-updating.md) | Beta priors, re-bucketing after each repayment, transition matrices, and why one late payment can demote a prime customer |
| 07 | [Markov decision processes](07-markov-decision-processes.md) | States, actions, policies, weakly coupled MDPs, and what λ* means |
| 08 | [The optimisation model](08-the-optimisation-model.md) | The Bellman equations term by term, the terminal value, and a full worked decision with real parameters |
| 09 | [Lagrangian, backward induction and Beta-Binomial](09-lagrangian-backward-induction-beta-binomial.md) | Derivations of the three core techniques, each checked against the model |
| 10 | [Monte Carlo simulation](10-monte-carlo-simulation.md) | How the simulator works, common random numbers, precision, and limits |

## Part 3. Results and stress tests

| # | Note | What it covers |
|---|---|---|
| 11 | [Macro scenarios](11-macro-scenarios.md) | Base, adverse and benign economies, how the economy reaches the model, and the robustness test |
| 12 | [Sensitivity analysis](12-sensitivity-analysis.md) | Which assumptions move NPV most, row by row, and which claims the runs support |
| 13 | [Raising profit and lowering defaults](13-raising-profit-and-lowering-defaults.md) | Nudges, step size, bandits, risk-based pricing and offline RL: what was tested and what is a proposal |
| 14 | [Macro data vs assumptions](14-macro-data-vs-assumptions.md) | Official Kenyan data against the model's inputs, and how to describe the capital limit correctly |

## From research to production

How this repository deploys the model: [architecture](../architecture.md), [assumptions log](../assumptions.md), [model card](../model_card.md), [roadmap](../roadmap.md).
