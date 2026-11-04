"""An LLM flag alone cannot turn an IPO plan into a completed listing."""

import re


def confirms_invalid_private_metric(evidence):
    if evidence.synthetic:
        return True  # Explicit synthetic settlement tests use supplied ground truth.
    if evidence.claim_kind != "fact" or evidence.valuation_status == "proposed":
        return False
    quote = evidence.support_quote
    if not quote or re.search(
        r"aiming|planning|preparing|plans to|could|may |draft prospectus", quote, re.I
    ):
        return False
    return bool(
        re.search(
            r"OpenAI(?:\s+has|\s+had|\s+officially|\s+successfully|\s+today|\s+shares|['’]s shares){0,3}\s+"
            r"(?:completed (?:its |the )?(?:IPO|initial public offering)|went public|began trading|started trading|"
            r"is (?:now )?publicly traded|ceased to be a private company)",
            quote,
            re.I,
        )
    )
