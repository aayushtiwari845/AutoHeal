# AutoHeal Studio viva preparation

Joint submission: **Aayush Kumar Tiwari — 16014223003 — LY AI & DS B2** and **Prateeksha Kini — 16014223061 — LY AI & DS B3**.

1. **What does the project do?** It asks a local coding model for Python, executes each candidate in a constrained child process, evaluates its output and supplies concrete failure evidence for a repair. It stops on success, cancellation, provider failure or at most five attempts.

2. **How does this relate to ReAct and Reflexion?** The application alternates model proposals with execution observations, following the ReAct pattern. Feedback and concise technical diagnoses influence later attempts without changing model weights, which is the relevant Reflexion idea. It is not a full reproduction of either research framework.

3. **Why use Qwen2.5 Coder 7B?** It is a code-specialized instruction model that can run through the installed Ollama service on this laptop. Local inference requires no hosted API key. The selected checkpoint is distinct from Qwen3 4B and the other already-selected models.

4. **Which parts are actually generated?** In live mode, the model generates normal candidates and repairs. If the controlled first failure is selected, that first source is prewritten and marked seeded; subsequent live repairs come from Ollama. Scripted replay uses predetermined broken and repaired sources, and is explicitly labelled.

5. **What are the loop phases?** Generate, execute, evaluate, reflect and done. The run manager stores timestamped phase events and per-attempt code, diagnosis, stdout, stderr, exit code, execution duration, error, feedback and validation.

6. **How is success determined?** A preset must execute without failure, print exactly one valid JSON value, and match the independently specified expected structure and values. A zero exit code does not establish correct logic. A custom task only checks a non-empty JSON object and is labelled structurally validated.

7. **What is a runtime error in the sales case?** The seeded program attempts `sum(row['amount'] for row in DATA)`. The raw amounts are strings, so adding them to sum's initial integer causes TypeError on line 1. The repair parses numeric values, rejects invalid rows and preserves the negative adjustment.

8. **What is the text case error?** Python strings provide `lower()`, not `lowercase()`. The seeded call raises AttributeError. A correct repair then uses contiguous ASCII letters, normalizes tokens and sorts equal counts alphabetically.

9. **What is a logical error in the grades case?** A simple average runs without an exception but ignores the 20%, 30% and 50% weights. Another authentic live error chose the alphabetically first passing name as highest. Correct highest means maximum unrounded weighted score; alphabetic order applies only when greatest scores tie.

10. **Why retain a failed live run?** It shows that the loop does not guarantee convergence. The original fully generated grade run repaired malformed syntax but repeatedly preserved a wrong highest calculation and exhausted five attempts. Keeping its trace supports an honest analysis of failure and the feedback improvement.

11. **How did feedback improve after that failure?** Semantic feedback now identifies bounded field paths such as `$.highest` and restates the associated task rule, rather than only saying the output differs. It does not supply expected answer values to the model. The task clarifies the greatest-score rule, every rejected sales row must be counted, and the system reinforces that DATA is already loaded. Intermediate retests still showed a sales failure, so the complete evidence includes the final regression outcomes as well.

12. **Are syntax errors always non-recoverable?** No. A later candidate can usually repair missing punctuation, indentation or an unterminated string. A failure is effectively non-recoverable within a run when the attempt budget is exhausted, the provider is unavailable, required capabilities are disallowed, or no correctness oracle can establish success.

13. **What exact evidence reaches the model?** Current task and DATA, the latest candidate, error type/message/line, exit code, bounded stdout and stderr, duration and validation field paths with their contract rules. Repair uses the original user task, the previous assistant candidate, and a new user feedback message. Full old logs are not accumulated. Expected reference answer values are excluded from the repair context.

14. **Why truncate and deduplicate logs?** Repeated output can consume context without adding evidence. The executor caps captured streams and condenses adjacent repeated lines. Provider feedback limits stdout to 1200 characters, stderr to 1800 and the full feedback envelope to 3500 characters.

15. **What happens on an infinite loop?** The parent monitors the child and kills it when the configured execution bound expires, at most five seconds. TimeoutError is recorded and can guide a more efficient candidate. Model generation has a separate, longer transport bound; the five-second limit is not a total-run limit.

16. **Is this a secure sandbox?** It is a defense-in-depth constrained subprocess for trusted local lab tasks. AST/import/builtin restrictions, an audit hook, secret-free environment, isolated temporary directory, output caps and Windows Job Object reduce risk. It is not a hard OS security boundary and must not execute hostile public submissions.

17. **What does the Windows Job Object do?** When assignment succeeds, it caps process memory at 384 MB, restricts the job to one active process and kills the job on close. Each attempt exposes `job_limit_active`; the program does not claim the OS restriction worked when it did not.

18. **What if Ollama stops or the user cancels?** An unavailable provider produces provider_error and preserves the failed trace. Cancellation immediately changes run status, closes an active provider stream and kills an executing child. Delayed model output cannot convert a cancelled run into success. A worker retains one of the two capacity slots until its cleanup finishes, so repeated cancellation cannot create unbounded background work.

19. **How were expected answers independently checked?** Tests recompute numeric references using Decimal arithmetic and token statistics through a separate counting implementation. The validator checks expected keys, finite numeric values, stable lists and tight numeric tolerance. Fixed public examples do not prove generalization; varied and hidden tests would strengthen the evaluation.

20. **What should you say about the results and ethics?** Report the saved traces, including exhaustion, and distinguish real live generation from scripted replay. Do not apply published model benchmark scores to this local quantized runtime. Prompts and exported traces may contain sensitive information even though inference is local. Acknowledge AI assistance and be able to explain the source and the error mechanics yourselves.

Primary reading: [ReAct](https://arxiv.org/abs/2210.03629), [Reflexion](https://arxiv.org/abs/2303.11366), [Python subprocess](https://docs.python.org/3/library/subprocess.html), [Ollama chat API](https://docs.ollama.com/api/chat), [Qwen official model card](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct).
