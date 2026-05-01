import re
import math
from typing import List

def parse_weight_to_grams(weight_str: str) -> float:
    if not weight_str:
        return 0.0
    weight_str_lower = weight_str.lower().replace(" ", "")
    
    # Find ALL weight values in the string (handles ranges like "900g-1kg" or "900g - 1kg")
    all_matches = re.findall(r'([\d.]+)(kg|g|l|ml)', weight_str_lower)
    if not all_matches:
        return 0.0
    
    # Convert all found weights to grams and return the MAXIMUM
    # (for ranges like "900g-1kg", the pack is effectively ~1kg, not 900g)
    grams_values = []
    for val_str, unit in all_matches:
        val = float(val_str)
        if unit in ['kg', 'l']:
            grams_values.append(val * 1000.0)
        else:
            grams_values.append(val)
    
    return max(grams_values)


def calculate_adjusted_quantity(requested_weight: str, matched_name: str, base_quantity: int = 1) -> int:
    if not requested_weight:
        return base_quantity
        
    req_g = parse_weight_to_grams(requested_weight)
    if req_g <= 0:
        return base_quantity
        
    matched_g = parse_weight_to_grams(matched_name)
    if matched_g <= 0:
        return base_quantity
        
    multiplier = math.ceil(req_g / matched_g)
    
    return base_quantity * int(multiplier)

def parse_pieces_from_name(name: str) -> int:
    if not name:
        return 0
    name_lower = name.lower()
    
    # Prioritize exact piece indicators anywhere in the string
    match = re.search(r'(\d+)\s*(?:pcs|pc|pieces|units|eggs)(?!\w)', name_lower)
    if match: return int(match.group(1))
    
    match = re.search(r'(?:pack|set)\s*of\s*(\d+)', name_lower)
    if match: return int(match.group(1))
    
    # Fallback to pack counts if no piece counts are found
    match = re.search(r'(\d+)\s*(?:pack|set)(?!\w)', name_lower)
    if match: return int(match.group(1))
    
    return 0

def get_final_quantity(item, matched_name: str) -> int:
    """
    Returns how many units to add to cart to satisfy the user's requirement.
    If the user asked for 2kg and the product is 500g, we add 4 units.
    """
    req_qty = item.quantity
    
    # If the user specified a weight, adjust quantity based on packet size
    if item.weight:
        req_g = parse_weight_to_grams(item.weight)
        if req_g > 0:
            matched_g = parse_weight_to_grams(matched_name)
            if matched_g > 0:
                multiplier = math.ceil(req_g / matched_g)
                return req_qty * int(multiplier)
    
    # For piece-based items (eggs etc.) with no weight specified, adjust for pack size
    matched_pieces = parse_pieces_from_name(matched_name)
    if matched_pieces > 1:
        packs_needed = math.ceil(req_qty / matched_pieces)
        return packs_needed
    
    return req_qty

def get_requested_pieces(item) -> int:
    # If the user asks for a quantity and it has no weight attached to it, 
    # and the category isn't typically sold by weight, return requested pieces.
    if item.weight:
        return 0
    return item.quantity

def normalize_query_words(query: str) -> List[str]:
    """
    Splits the query into words, and stems plurals to singulars
    to prevent overlapping substring score inflation.
    """
    words = query.lower().split()
    normalized = set()
    for w in words:
        if len(w) > 3:
            if w.endswith('oes'):
                normalized.add(w[:-2]) # tomatoes -> tomato, potatoes -> potato
            elif w.endswith('es') and not w.endswith('oes'):
                normalized.add(w[:-2] if w[-3] != 'l' else w) # avoid apples -> appl
            elif w.endswith('s') and not w.endswith('ss'):
                normalized.add(w[:-1]) # eggs -> egg
            else:
                normalized.add(w)
        else:
            normalized.add(w)
    return list(normalized)
