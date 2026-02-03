from datetime import date, datetime
from typing import List, Tuple, Optional

def get_financial_year_start_end(year: int) -> Tuple[date, date]:
    """
    Get the start and end dates for a financial year.
    Financial year runs from 1st April (year) to 31st March (year+1)
    
    Args:
        year: The starting year of the financial year (e.g., 2025 for FY 2025-26)
    
    Returns:
        Tuple of (start_date, end_date)
    """
    start_date = date(year, 4, 1)
    end_date = date(year + 1, 3, 31)
    return start_date, end_date

def get_current_financial_year() -> int:
    """
    Get the current financial year based on today's date.
    Returns the starting year of the current financial year.
    """
    today = date.today()
    if today.month >= 4:  # April to December
        return today.year
    else:  # January to March
        return today.year - 1

def generate_financial_year_options(start_year: Optional[int] = None, end_year: Optional[int] = None) -> List[dict]:
    """
    Generate a list of financial year options for dropdown.
    
    Args:
        start_year: Starting year (default: 10 years ago)
        end_year: Ending year (default: current year + 1)
    
    Returns:
        List of dicts with 'value' (year) and 'label' (formatted string)
    """
    if end_year is None:
        end_year = get_current_financial_year() + 1
    
    if start_year is None:
        start_year = end_year - 10  # Show last 10 years by default
    
    options = []
    for year in range(end_year, start_year - 1, -1):  # Reverse order (newest first)
        label = f"1st April {year} - 31st March {year + 1}"
        options.append({
            'value': year,
            'label': label
        })
    
    return options

def filter_by_financial_year(queryset, year: int, date_field: str = 'dep_date'):
    """
    Filter a queryset by financial year based on a date field.
    
    Args:
        queryset: Django queryset to filter
        year: Financial year starting year (e.g., 2025 for FY 2025-26)
        date_field: Name of the date field to filter on (default: 'dep_date')
    
    Returns:
        Filtered queryset
    """
    start_date, end_date = get_financial_year_start_end(year)
    
    # Build the filter dynamically
    filter_kwargs = {
        f'{date_field}__gte': start_date,
        f'{date_field}__lte': end_date
    }
    
    return queryset.filter(**filter_kwargs)
