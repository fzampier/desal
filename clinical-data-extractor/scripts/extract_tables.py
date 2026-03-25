#!/usr/bin/env python3
"""
Extract tables from PDF and create structured lookup for verification.
"""

import camelot
import pdfplumber
import re
import json
import sys
from pathlib import Path


def extract_numbers_from_cell(cell_text):
    """Extract all numbers from a cell."""
    if not cell_text:
        return []
    # Handle newline-separated values
    cell_text = str(cell_text).replace('\n', ' ')
    # Find all numbers (including decimals, negatives)
    numbers = re.findall(r'-?\d+\.?\d*', cell_text)
    return numbers


def extract_tables_camelot(pdf_path, pages='all'):
    """Extract tables using Camelot (better for structured tables)."""
    tables_data = []
    
    try:
        # Try stream mode (for borderless tables common in journals)
        tables = camelot.read_pdf(str(pdf_path), pages=pages, flavor='stream')
        
        for table in tables:
            if table.accuracy < 50:  # Skip low-quality extractions
                continue
                
            df = table.df
            table_info = {
                'page': table.page,
                'accuracy': table.accuracy,
                'cells': [],
                'numbers': set()
            }
            
            # Extract all cells with context
            for row_idx, row in df.iterrows():
                for col_idx, cell in enumerate(row):
                    cell_text = str(cell).strip() if cell else ''
                    if cell_text:
                        numbers = extract_numbers_from_cell(cell_text)
                        for num in numbers:
                            table_info['cells'].append({
                                'row': row_idx,
                                'col': col_idx,
                                'text': cell_text[:100],  # Truncate
                                'number': num
                            })
                            table_info['numbers'].add(num)
            
            table_info['numbers'] = list(table_info['numbers'])
            tables_data.append(table_info)
            
    except Exception as e:
        print(f"Camelot extraction failed: {e}", file=sys.stderr)
    
    return tables_data


def extract_tables_pdfplumber(pdf_path):
    """Fallback extraction using pdfplumber."""
    tables_data = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    table_info = {
                        'page': page_num,
                        'accuracy': None,
                        'cells': [],
                        'numbers': set()
                    }
                    
                    for row_idx, row in enumerate(table):
                        for col_idx, cell in enumerate(row):
                            cell_text = str(cell).strip() if cell else ''
                            if cell_text:
                                numbers = extract_numbers_from_cell(cell_text)
                                for num in numbers:
                                    table_info['cells'].append({
                                        'row': row_idx,
                                        'col': col_idx,
                                        'text': cell_text[:100],
                                        'number': num
                                    })
                                    table_info['numbers'].add(num)
                    
                    table_info['numbers'] = list(table_info['numbers'])
                    tables_data.append(table_info)
                    
    except Exception as e:
        print(f"pdfplumber extraction failed: {e}", file=sys.stderr)
    
    return tables_data


def build_number_lookup(tables_data):
    """Build a lookup: number -> list of table locations."""
    lookup = {}
    
    for table_idx, table in enumerate(tables_data):
        for cell in table['cells']:
            num = cell['number']
            if num not in lookup:
                lookup[num] = []
            lookup[num].append({
                'table': table_idx + 1,
                'page': table['page'],
                'row': cell['row'],
                'col': cell['col'],
                'context': cell['text']
            })
    
    return lookup


def extract_and_save(pdf_path, output_path=None):
    """Main extraction function."""
    pdf_path = Path(pdf_path)
    
    if output_path is None:
        output_path = pdf_path.with_suffix('.tables.json')
    
    # Try Camelot first
    print(f"Extracting tables from {pdf_path}...")
    tables = extract_tables_camelot(pdf_path)
    
    # Fallback to pdfplumber if Camelot fails
    if not tables:
        print("Camelot failed, trying pdfplumber...")
        tables = extract_tables_pdfplumber(pdf_path)
    
    # Build lookup
    lookup = build_number_lookup(tables)
    
    result = {
        'source': str(pdf_path),
        'tables_count': len(tables),
        'unique_numbers': len(lookup),
        'tables': tables,
        'number_lookup': lookup
    }
    
    # Save
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"Extracted {len(tables)} tables with {len(lookup)} unique numbers")
    print(f"Saved to: {output_path}")
    
    return result


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python extract_tables.py <pdf_path> [output_path]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    extract_and_save(pdf_path, output_path)
