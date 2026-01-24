import json


dictionary = {
  "Type-Token Ratio (TTR)": {
    "description": "Measures lexical diversity (uniqueness of vocabulary).",
    "calculation_method": "len(unique_words) / word_count",
    "assessments": [
      {
        "threshold": "> 0.60",
        "label": "diverse",
        "interpretation": "High vocabulary richness; precise descriptions; avoids repeating words."
      },
      {
        "threshold": "> 0.40",
        "label": "standard",
        "interpretation": "Typical balance of new vocabulary and repeated function words."
      },
      {
        "threshold": "≤ 0.40",
        "label": "repetitive",
        "interpretation": "Limited vocabulary; relies heavily on same words; common in simple primers or redundant speech."
      }
    ]
  },
  "Mean Length of Sentence (MLS)": {
    "description": "Average sentence length; indicates syntactic complexity.",
    "calculation_method": "word_count / sentence_count",
    "assessments": [
      {
        "threshold": "> 25",
        "label": "complex/elaborate",
        "interpretation": "Academic/formal style; uses multiple clauses and detailed qualifiers."
      },
      {
        "threshold": "> 15",
        "label": "standard",
        "interpretation": "Balanced flow suitable for general readers or journalism."
      },
      {
        "threshold": "≤ 15",
        "label": "short/telegraphic",
        "interpretation": "Punchy, direct, or fragmented style; typical of dialogue or action scenes."
      }
    ]
  },
  "Punctuation Density": {
    "description": "Frequency of punctuation marks per 1,000 words.",
    "calculation_method": "(punct_count / word_count) * 1000",
    "assessments": [
      {
        "threshold": "> 150",
        "label": "heavily punctuated",
        "interpretation": "Complex structure with many pauses, lists, or clauses (commas, semicolons)."
      },
      {
        "threshold": "> 100",
        "label": "balanced",
        "interpretation": "Standard grammatical pacing."
      },
      {
        "threshold": "≤ 100",
        "label": "sparse",
        "interpretation": "Long, flowing run-on sentences or simple 'subject-verb-object' structures with few breaks."
      }
    ]
  },
  "Discourse Marker Density": {
    "description": "Frequency of fillers (e.g., 'like', 'well').",
    "calculation_method": "(count(markers) / word_count) * 1000",
    "assessments": [
      {
        "threshold": "> 40",
        "label": "conversational",
        "interpretation": "Spoken-style spontaneity; 'thinking out loud'; high informality."
      },
      {
        "threshold": "> 15",
        "label": "natural",
        "interpretation": "Relaxed writing that mimics speech without excess clutter."
      },
      {
        "threshold": "≤ 15",
        "label": "formal/polished",
        "interpretation": "Edited, scripted, or academic text; strictly avoids fillers."
      }
    ]
  },
  "Hapax Legomena Ratio": {
    "description": "Ratio of words appearing exactly once (uniqueness).",
    "calculation_method": "count(freq==1) / len(unique_words)",
    "assessments": [
      {
        "threshold": "> 0.60",
        "label": "unique/creative",
        "interpretation": "Highly descriptive or literary; constantly introduces new concepts/terms."
      },
      {
        "threshold": "> 0.40",
        "label": "rich",
        "interpretation": "Good variety; engaging but grounded."
      },
      {
        "threshold": "≤ 0.40",
        "label": "basic/repetitive",
        "interpretation": "Relies on a small core set of 'anchor' words; predictable."
      }
    ]
  },
  "Formulaic Density": {
    "description": "Reliance on repeated phrases/n-grams.",
    "calculation_method": "sum(repeated_counts) / word_count",
    "assessments": [
      {
        "threshold": "> 0.30",
        "label": "highly formulaic",
        "interpretation": "Relies on clichés, idioms, or repetitive rhetoric (e.g., political speeches)."
      },
      {
        "threshold": "> 0.10",
        "label": "standard",
        "interpretation": "Uses common collocations (e.g., 'in the end')."
      },
      {
        "threshold": "≤ 0.10",
        "label": "original",
        "interpretation": "Novel phrasing; avoids stock phrases or predictable patterns."
      }
    ]
  },
  "Modal Hedging Ratio": {
    "description": "Frequency of uncertainty markers (e.g., 'could').",
    "calculation_method": "count(hedges) / sentence_count",
    "assessments": [
      {
        "threshold": "> 0.20",
        "label": "tentative/hedged",
        "interpretation": "Cautious, scientific, or polite; avoids absolute claims."
      },
      {
        "threshold": "> 0.05",
        "label": "balanced",
        "interpretation": "Mixes facts with appropriate caution."
      },
      {
        "threshold": "≤ 0.05",
        "label": "assertive/direct",
        "interpretation": "Authoritative, factual, or commanding; expresses high certainty."
      }
    ]
  },
  "Flesch Reading Ease": {
    "description": "Standard readability score (0–100 scale).",
    "calculation_method": "textstat.flesch_reading_ease",
    "assessments": [
      {
        "threshold": "> 80",
        "label": "very easy",
        "interpretation": "5th-grade level; simple words/sentences (children's books)."
      },
      {
        "threshold": "> 60",
        "label": "easy/standard",
        "interpretation": "Conversational/Standard English."
      },
      {
        "threshold": "> 40",
        "label": "difficult",
        "interpretation": "Intellectual/College level."
      },
      {
        "threshold": "≤ 40",
        "label": "technical",
        "interpretation": "Academic papers or legal contracts; requires specialized knowledge."
      }
    ]
  },
  "Common Vocabulary": {
    "description": "The top 10 most frequently occurring individual words in the text.",
    "calculation_method": "Counter(words).most_common(10)",
    "assessments": [
      {
        "threshold": "N/A",
        "label": "list[str]",
        "interpretation": "These words represent the core lexicon of the author. The AI should prioritize using these specific terms to mimic the author's idiosyncratic voice and preferred vocabulary."
      }
    ]
  },
  "Frequent Phrases": {
    "description": "The top 10 most frequently repeated n-grams (phrases of 2-4 words).",
    "calculation_method": "Counter(ngrams).most_common(10)",
    "assessments": [
      {
        "threshold": "N/A",
        "label": "list[str]",
        "interpretation": "These phrases represent the author's 'crutch' phrases or stylistic habits. The AI should weave these specific sequences into generated text to preserve the original rhythmic and rhetorical signature."
      }
    ]
  }
}