"""One small door to TypeSafe's System One API, standard library only.

This is a trimmed copy of a client written for a separate measurement project, bundled here
so the optional reranker in `jev_rerank.py` has no install step and no dependency. You do
not need it to use this benchmark; nothing else imports it.

What it enforces, so a caller does not have to remember:

  * The key is read from `TYPESAFE_API_KEY` in the environment, or from a `.env.local` file
    in the working directory. It is never printed, never logged, and leaves the process only
    as an Authorization header.
  * Every call is appended to a ledger file (`ledger.jsonl` by default, or `JEV_LEDGER`):
    time, tag, model, tokens, milliseconds. Never the text that was sent.
  * Spend is capped. `JEV_SPEND_CAP_USD` sets the cap and the default is two dollars. At the
    cap, `ask` refuses rather than spending more.
  * `JEV_DRY_RUN=1` sends nothing. It estimates the token count, writes a dry run row to the
    ledger, and returns flat placeholder answers, so a harness can be built and exercised
    with no key and no network.
  * The model is pinned to a version rather than a moving alias, so numbers stay comparable.

API shape, from the vendor's published documentation:
  POST https://api.typesafe.ai/v1/systemone
  {state, model, questions: {id: {type, instructions, criteria}}}
  types: noul gives {noul}; choice gives {choice, probabilities, confidence}
"""

import json
import os
import time
import urllib.error
import urllib.request

API = "https://api.typesafe.ai/v1"
MODEL = "jev-1.13.0"
USD_PER_MTOK = 0.042
DEFAULT_CAP_USD = 2.00


class JevError(RuntimeError):
    pass


def ledger_path():
    return os.environ.get("JEV_LEDGER") or os.path.join(os.getcwd(), "ledger.jsonl")


def _key():
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        path = os.environ.get("JEV_ENV_FILE") or os.path.join(os.getcwd(), ".env.local")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    name, _, value = line.strip().partition("=")
                    if name.strip() == "TYPESAFE_API_KEY":
                        key = value.strip().strip('"').strip("'")
    if not key:
        raise JevError("No API key. Put TYPESAFE_API_KEY in the environment or in .env.local.")
    return key


def spent():
    """(input tokens, dollars) across every real call in the ledger."""
    tokens = 0
    path = ledger_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not row.get("dry_run"):
                    tokens += int(row.get("input_tokens") or 0)
    return tokens, tokens / 1e6 * USD_PER_MTOK


def _log(row):
    with open(ledger_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _request(method, path, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
    delay = 1.0
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="ignore")[:600]
            if err.code in (429, 529) and attempt < 5:
                wait = float(err.headers.get("retry-after") or delay)
                time.sleep(min(wait, 30))
                delay *= 2
                continue
            raise JevError("HTTP %s: %s" % (err.code, detail))
        except urllib.error.URLError as err:
            if attempt < 5:
                time.sleep(delay)
                delay *= 2
                continue
            raise JevError("network: %s" % (err.reason,))
    raise JevError("gave up after six attempts")


def dry_run():
    return os.environ.get("JEV_DRY_RUN") == "1"


def ask(state, questions, tag="untagged", model=MODEL, timeout=60):
    """One request. Returns {question_id: answer}. Logs usage and refuses past the cap."""
    cap = float(os.environ.get("JEV_SPEND_CAP_USD", DEFAULT_CAP_USD))
    _, dollars = spent()
    if dollars >= cap:
        raise JevError("Spend cap reached: $%.4f of $%.2f. Stop and report." % (dollars, cap))
    body = {"state": state, "model": model, "questions": questions}
    started = time.time()
    if dry_run():
        estimate = len(json.dumps(body)) // 4
        _log({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tag": tag, "model": model,
              "dry_run": True, "input_tokens": estimate, "output_tokens": 0, "ms": 0,
              "questions": len(questions)})
        out = {}
        for qid, q in questions.items():
            if q.get("type") == "noul":
                out[qid] = {"type": "noul", "noul": 0.5}
            elif q.get("type") == "choice":
                options = list(q.get("criteria") or {"other": ""})
                out[qid] = {"type": "choice", "choice": options[0], "confidence": 0.0,
                            "probabilities": dict((o, 1.0 / len(options)) for o in options)}
            else:
                levels = max(1, len(q.get("criteria") or {}))
                out[qid] = {"type": "score", "score": (levels - 1) / 2.0, "confidence": 0.0}
        return out
    response = _request("POST", "/systemone", body, timeout=timeout)
    usage = response.get("usage") or {}
    _log({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tag": tag,
          "model": response.get("model", model), "input_tokens": usage.get("input_tokens"),
          "output_tokens": usage.get("output_tokens"),
          "ms": int((time.time() - started) * 1000), "questions": len(questions)})
    return response.get("answers") or {}
