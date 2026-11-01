"""Binary pixel metrics shared by training validation and checkpoint evaluation."""

import torch


def confusion_counts(logits, masks, threshold=0.5):
    predictions, labels = logits.sigmoid() >= threshold, masks >= 0.5
    return torch.stack(((predictions & labels).sum(), (predictions & ~labels).sum(),
                        (~predictions & labels).sum(), (~predictions & ~labels).sum()))


def metrics_from_counts(counts):
    """Global pixel metrics from TP, FP, FN, TN. Both-empty sets score 1.

    Undefined precision/recall score 0 when only one foreground set is empty.
    """
    tp, fp, fn, tn = (int(value) for value in counts)
    both_empty = tp + fp + fn == 0
    return {
        "dice": 2 * tp / (2 * tp + fp + fn) if not both_empty else 1.0,
        "iou": tp / (tp + fp + fn) if not both_empty else 1.0,
        "precision": tp / (tp + fp) if tp + fp else float(both_empty),
        "recall": tp / (tp + fn) if tp + fn else float(both_empty),
    }
