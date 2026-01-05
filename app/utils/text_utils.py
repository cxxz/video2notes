"""
Text analysis utility functions for Video2Notes application.
"""
from typing import Dict, Tuple, List

import scrubadub
import scrubadub_spacy


def analyze_text_for_names(text: str, threshold: float = 0.65) -> Tuple[bool, Dict, List[str]]:
    """Analyze text to determine if it consists mostly of names.

    Uses scrubadub with SpaCy to detect names and calculate the proportion
    of the text that consists of named entities.

    Args:
        text: The input text to analyze
        threshold: The proportion of text that needs to be names to return True (default: 0.65)

    Returns:
        Tuple containing:
        - Boolean indicating if text is mostly names
        - Dictionary with detected entities and their counts
        - List of detected names
    """
    # Initialize scrubber with SpacyNameDetector
    scrubber = scrubadub.Scrubber()

    # Clean the text and get the filth
    cleaned_text = scrubber.clean(text)

    scrubber.add_detector(scrubadub_spacy.detectors.SpacyNameDetector(model='en_core_web_lg'))
    filth_list = list(scrubber.iter_filth(text))

    # Count the different types of entities
    entity_counts: Dict[str, int] = {}
    name_chars = 0

    non_whitespace_chars = sum(
        1 for char in cleaned_text
        if not char.isspace() and char not in [',', '.', '<', '>', '\n']
    )

    names: List[str] = []

    for filth in filth_list:
        if filth.type not in entity_counts:
            entity_counts[filth.type] = 0
        entity_counts[filth.type] += 1

        # Count characters that are names
        if filth.type == 'name':
            name_chars += len(filth.text)
            names.append(filth.text)

        if filth.type == 'organization':
            non_whitespace_chars -= len(filth.text)

    # Calculate the proportion of text that is names
    name_proportion = name_chars / non_whitespace_chars if non_whitespace_chars > 0 else 0

    # Determine if text is mostly names
    is_mostly_names = name_proportion >= threshold

    return is_mostly_names, entity_counts, names
