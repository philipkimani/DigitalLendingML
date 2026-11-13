# Can Uptake Be Predicted?

How the logistic regression and LightGBM checks were run, what each check means, and how to read the results. The conclusion (no feature predicts uptake) decides how acceptance is modelled in the rest of the project.

## 1. The question being tested

The problem asks for a model that predicts customer uptake of limit increases. Before building one, a simpler question comes first: **do any of the features in the file carry information about uptake at all?**

The file has three possible predictors:
- **loan**: initial loan amount
- **days**: days since last loan
- **ontime**: on-time repayment percentage

The outcome is the number of increases each customer took in 2023 (0, 3, 4 or 5).

The main test is framed as a yes/no classification: **did the customer take any increase?** About 44% took none and 56% took some, so the classes are reasonably balanced.

If the answer is "no information", a feature-based uptake model would only fit noise. That finding changes the modelling approach, which is why it is worth testing properly.

## 2. The two models, and why both

| Model | What it can find | Why include it |
|---|---|---|
| **Logistic regression** | Straight-line (monotonic) relationships, e.g. "higher on-time rate → more likely to take an increase" | The standard, interpretable credit-modelling baseline. If a simple relationship exists, it finds it. |
| **LightGBM** (gradient-boosted trees) | Non-linear patterns and interactions, e.g. "small loans *and* recent borrowers" | A flexible model. If logistic regression misses a curved or combined pattern, LightGBM would catch it. |

Using both covers the two ways a signal could hide: a simple trend, or a complex pattern. If **both** fail, the "no signal" conclusion is much stronger than if only one did.

## 3. The metric: AUC

**AUC (area under the ROC curve)** measures how well a model ranks customers. Pick one customer who took an increase and one who did not, at random. AUC is the probability that the model gives the taker the higher score.

| AUC | Meaning |
|---|---|
| 0.5 | No better than a coin flip: the model cannot tell takers from non-takers |
| 0.6–0.7 | Weak but real signal (common in early credit models) |
| 0.7–0.8 | Good |
| above 0.8 | Strong |

A related credit-industry measure is **Gini = 2 × AUC − 1**. An AUC of 0.5 is a Gini of 0, meaning no discriminating power.

**Why AUC rather than accuracy?** Accuracy depends on the cut-off and on class balance. AUC measures ranking ability across all cut-offs, which is what matters when the score decides who gets an offer.

## 4. Cross-validation: testing on data the model has not seen

A model always looks better on the data it was trained on. **5-fold cross-validation** guards against that:

1. Split the 30,000 customers into five equal parts (folds).
2. Train on four folds, test on the fifth.
3. Repeat five times so each fold is the test set once.
4. Average the five test scores.

**Stratified** folds keep the same share of takers in each fold. **Shuffled** folds mix the rows randomly first, so any ordering in the file (for example, by customer ID) cannot affect the result.

## 5. The results, one check at a time

### Check 1: the first test

Three raw features, 5-fold cross-validation in file order, default settings.

**Result:** logistic AUC 0.503, LightGBM AUC 0.501.

### Check 2: the stronger re-run

Scaled features for the logistic regression (so no feature dominates because of its units), with shuffled, stratified folds.

| Model | Mean AUC | Range across the five folds |
|---|---|---|
| Logistic regression | 0.500 | 0.491 – 0.508 |
| LightGBM | 0.502 | 0.494 – 0.511 |

**How to read it:** the fold scores sit on both sides of 0.5. A real but weak signal would keep every fold above 0.5. Scores scattered around 0.5 are what pure noise looks like.

### Check 3: the permutation test (the strongest evidence)

**The idea:** if the features genuinely predict uptake, the model should score better on the real labels than on labels that have been randomly shuffled, which have no link to the features by construction.

**The procedure:**
1. Score the model on the real labels (AUC 0.500).
2. Shuffle the labels randomly, refit and score. Repeat 100 times. This builds a picture of what "no signal" looks like for this dataset and model.
3. The p-value is the share of shuffled runs that scored as well as or better than the real labels.

**Result:** real AUC 0.500; shuffled AUC 0.500 ± 0.006; **p = 0.55**.

**How to read it:** p = 0.55 means more than half the random shufflings did as well as the real data. The real labels are indistinguishable from random ones. A genuine signal would give p below 0.05.

**Why this is the strongest check:** it does not rely on the rule of thumb that "0.5 means random". It measures what chance looks like for this exact data and model, then compares.

### Check 4: leakage

**Leakage** is when information slips into the model that would not be available in reality, making it look better than it is. A common source is row order or an ID that correlates with the outcome.

Adding the customer ID as a feature to LightGBM gives AUC 0.502, unchanged. There is no hidden ordering or ID pattern.

### Check 5: predicting how many, not just whether

The binary target could hide signal in the count. Perhaps features cannot predict *whether* someone takes an increase, but can predict *how many*. Among the 16,793 customers who took any, the model tries to predict 3 vs 4 vs 5.

**Result:** 33.2% accuracy, against 33.7% from always guessing the most common count. No better than guessing.

### Check 6: rank correlation

**Spearman correlation** measures whether two variables move together in rank order (it does not require a straight line). It runs from −1 to +1, with 0 meaning no relationship.

**Result:** loan −0.005, days 0.003, on-time −0.001. All effectively zero.

## 6. What the evidence adds up to

Six different checks, two model types, two target definitions and a formal significance test all point the same way: **the three features carry no information about uptake.**

**What it means for the modelling:**
- No feature-based uptake model is built, because it would only fit noise.
- **Revealed behaviour** is used instead: each customer's own 2023 count gives their acceptance propensity, (n + 1) / 7, the Beta-Binomial estimate (see [note 09](09-lagrangian-backward-induction-beta-binomial.md)).
- In production, with real behavioural and transaction data, the same checks would be the first step. A real uptake model would very likely beat this baseline.

**The most likely reason:** the dataset is synthetic, generated with independent random columns. The features look independently generated, so they are not relied on for uptake.

The same audit also found that the profit column does not match the stated $40 per increase. That is a separate story: [The profit column puzzle](05-the-profit-column-puzzle.md).

## 7. Questions to check understanding

- **Were the models tuned?** Not heavily. The permutation test shows the real labels score the same as shuffled ones, so there is nothing to tune towards. Tuning can only overfit noise.
- **Why test at all?** To justify the modelling choice with evidence rather than assume it.
- **Could a deep learning model find something?** No model can find signal that is not in the data. If LightGBM, which captures non-linear interactions, finds nothing, a neural network on three features will not either.
- **What is a permutation test, in one sentence?** Shuffle the outcome to destroy any real link, refit many times, and see whether the real data does better than the shuffled versions.
- **What AUC is realistic in production?** For uptake on real transaction and behavioural data, 0.65–0.75 is a reasonable hope. The point here was to establish that this file gives no signal, not to set a target.
