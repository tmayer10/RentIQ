# RentIQ Chat Utils Test Suite

Comprehensive unit tests for the RentIQ chat utilities module.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Running Tests](#running-tests)
- [Test Coverage](#test-coverage)
- [Test Files](#test-files)
- [Writing New Tests](#writing-new-tests)
- [Continuous Integration](#continuous-integration)

## Overview

This test suite provides comprehensive coverage of the `chat_utils` module, including:

- **Filter extraction and normalization** (Tier 1 & Tier 2 filtering)
- **Scoring and ranking algorithms**
- **Multi-turn conversation logic**
- **Utility functions** (text building, metadata sanitization, deduplication)
- **Response routing** (new search vs. follow-up detection)

**Testing Philosophy:** We focus on testing **pure functions** and **business logic** without requiring external API calls or database connections. Integration tests with mocked dependencies are used sparingly.

## Installation

### Prerequisites

```bash
# Python 3.9+
python --version

# Install test dependencies
pip install pytest pytest-cov pytest-asyncio fakeredis
```

### Project Setup

```bash
cd /u/lamba/School\ Projects/RentIQ/RentIQ/chat_utils
```

## Running Tests

### Run All Tests

```bash
# From chat_utils/ directory
pytest tests/ -v
```

### Run Specific Test File

```bash
# Test a specific module
pytest tests/test_utils.py -v
pytest tests/test_scorer.py -v
pytest tests/test_filters_change.py -v
```

### Run with Coverage Report

```bash
# Generate coverage report
pytest tests/ --cov=. --cov-report=html --cov-report=term

# View HTML report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Run Specific Test Class or Function

```bash
# Run a specific test class
pytest tests/test_utils.py::TestBuildText -v

# Run a specific test function
pytest tests/test_scorer.py::TestScoreListing::test_perfect_match -v
```

### Verbose Output with Print Statements

```bash
# Show print statements and detailed output
pytest tests/ -v -s
```

### Run Tests Matching a Pattern

```bash
# Run all tests with "amenities" in the name
pytest tests/ -k amenities -v

# Run all tests for subway functionality
pytest tests/ -k subway -v
```

## Test Coverage

### Module Coverage Summary

| Module | Test File | Functions Tested | Coverage |
|--------|-----------|-----------------|----------|
| `utils.py` | `test_utils.py` | build_text, sanitize_metadata, deduplicate_matches | ✅ 100% |
| `filters_change.py` | `test_filters_change.py` | normalize_filter_dict, have_filters_changed | ✅ 100% |
| `scorer.py` | `test_scorer.py` | score_listing, score_listings | ✅ 100% |
| `response_router.py` | `test_response_router.py` | decide_response_type | ✅ 100% |
| `pinecone_filters.py` | `test_pinecone_filters_fallback.py` | _fallback_extract_pinecone_filters, _normalize_pinecone_filters | ✅ Fallback only |
| `post_filters.py` | N/A | parse_amenities, parse_neighborhoods, parse_subway_preferences | ⚠️ Requires API mocks |
| `rewriter.py` | N/A | rewrite_query | ⚠️ Requires API mocks |
| `session_store.py` | N/A | SessionStore class | ⚠️ Requires Redis |
| `rag_pipeline.py` | N/A | rag_search | ⚠️ Integration test |

**Legend:**
- ✅ Full coverage
- ⚠️ Requires mocked dependencies (not included in basic unit tests)
- N/A - Not yet implemented

### What's Tested

#### ✅ Core Business Logic (Unit Tests)

1. **Filter Normalization & Comparison** (`test_filters_change.py`)
   - Normalizing filter dictionaries for consistent comparison
   - Detecting changes in hard filters (price, beds, baths, sqft, zipcode)
   - Detecting changes in soft filters (amenities, neighborhoods, subway)
   - Backward compatibility with old filter format

2. **Scoring & Ranking** (`test_scorer.py`)
   - Scoring listings against search criteria
   - Handling perfect matches, partial matches, and mismatches
   - Identifying compromises (missing amenities, wrong neighborhood, etc.)
   - Sorting listings by relevance score

3. **Response Type Detection** (`test_response_router.py`)
   - Distinguishing new search queries from follow-up questions
   - Detecting price/bedroom/bathroom modifications
   - Recognizing amenity additions/removals
   - Identifying general clarification questions

4. **Utility Functions** (`test_utils.py`)
   - Building searchable text from database rows
   - Sanitizing metadata for Pinecone storage
   - Deduplicating search results
   - Type conversions (Decimal → float, etc.)

5. **Filter Extraction (Fallback)** (`test_pinecone_filters_fallback.py`)
   - Regex-based extraction of price, beds, baths, sqft, zipcode
   - Normalizing extracted filters to Pinecone format
   - Filtering out invalid fields

#### ⚠️ Not Tested (Requires Mocks/Integration)

1. **LLM-Based Parsing** (requires API mocks)
   - `parse_amenities()` with Gemini API
   - `parse_neighborhoods()` with Gemini API
   - `parse_subway_preferences()` with Gemini API
   - `extract_pinecone_filters()` with Gemini API
   - `rewrite_query()` with OpenAI API

2. **Session Storage** (requires Redis or fakeredis)
   - SessionStore class methods
   - Redis key management
   - TTL expiration

3. **Vector Search** (requires Pinecone)
   - `hybrid_search()` functionality
   - Embedding generation

4. **End-to-End RAG Pipeline** (integration test)
   - Full `rag_search()` workflow
   - Multi-turn conversation handling

## Test Files

### `conftest.py`
Pytest configuration and shared fixtures:
- `sample_listing_row`: Mock database row
- `sample_metadata`: Mock Pinecone metadata
- `mock_match`: Mock search result object
- `sample_chat_history`: Mock conversation history
- `sample_filter_state`: Mock filter state
- `create_filter_dict`: Factory for creating filter dicts
- `create_match`: Factory for creating mock matches

### `test_utils.py` (64 tests)
Tests for `utils.py`:
- `TestBuildText`: Building searchable text from database rows
- `TestSanitizeMetadata`: Cleaning metadata for storage
- `TestDeduplicateMatches`: Removing duplicate results

### `test_filters_change.py` (93 tests)
Tests for `filters_change.py`:
- `TestNormalizeFilterDict`: Filter normalization
- `TestHaveFiltersChanged`: Change detection (old & new format, hard & soft filters)

### `test_scorer.py` (82 tests)
Tests for `scorer.py`:
- `TestScoreListing`: Scoring individual listings
- `TestScoreListings`: Scoring and sorting multiple listings

### `test_response_router.py` (47 tests)
Tests for `response_router.py`:
- `TestDecideResponseType`: Routing between new search and follow-up

### `test_pinecone_filters_fallback.py` (38 tests)
Tests for `pinecone_filters.py` (fallback functions):
- `TestFallbackExtractPineconeFilters`: Regex-based filter extraction
- `TestNormalizePineconeFilters`: Filter normalization and validation

## Writing New Tests

### Test Structure

```python
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from your_module import your_function


class TestYourFunction:
    """Tests for your_function."""

    def test_basic_functionality(self):
        """Test the basic use case."""
        result = your_function(input_data)
        assert result == expected_output

    def test_edge_case(self):
        """Test an edge case."""
        result = your_function(edge_case_input)
        assert result is not None
```

### Using Fixtures

```python
def test_with_fixture(mock_match, sample_criteria):
    """Use fixtures defined in conftest.py."""
    score, compromises = score_listing(mock_match, sample_criteria)
    assert score > 0
```

### Parametrized Tests

```python
@pytest.mark.parametrize("query,expected", [
    ("2br under $3000", {"bedrooms": 2, "price": {"$lt": 3000}}),
    ("studio", {"bedrooms": 0}),
    ("3 bathrooms", {"bathrooms": 3.0}),
])
def test_multiple_cases(query, expected):
    result = extract_filters(query)
    assert result == expected
```

### Testing Async Functions

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_rag_search("query")
    assert result is not None
```

## Continuous Integration

### GitHub Actions (Example)

```yaml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.9

    - name: Install dependencies
      run: |
        pip install pytest pytest-cov
        pip install -r requirements.txt

    - name: Run tests
      run: |
        cd chat_utils
        pytest tests/ --cov=. --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

## Evaluation Metrics

### Code Coverage Targets

- **Core business logic**: 100% coverage (✅ Achieved)
- **Utility functions**: 100% coverage (✅ Achieved)
- **Integration functions**: 80%+ coverage (⚠️ Requires mocks)

### Test Quality Metrics

- **Total tests**: 324+ test cases
- **Test execution time**: < 2 seconds (unit tests only)
- **Test reliability**: 100% (no flaky tests)
- **Edge case coverage**: Extensive (empty inputs, None values, type conversions)

## Troubleshooting

### Common Issues

**Issue:** `ModuleNotFoundError: No module named 'chat_utils'`

**Solution:** Ensure you're running from the correct directory or add parent path:
```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**Issue:** Tests pass locally but fail in CI

**Solution:** Check Python version compatibility and ensure all dependencies are in `requirements.txt`

**Issue:** Coverage report shows missing lines

**Solution:** Add tests for edge cases, error handling, and boundary conditions

## Contributing

When adding new functionality to `chat_utils/`:

1. **Write tests first** (TDD approach)
2. **Achieve 100% coverage** for pure functions
3. **Use mocks** for external dependencies (API, DB, Redis)
4. **Document test cases** with clear docstrings
5. **Run full test suite** before committing

## Future Work

- [ ] Add integration tests with mocked LLM APIs
- [ ] Add session_store tests with fakeredis
- [ ] Add end-to-end RAG pipeline tests
- [ ] Add performance/load tests for scoring functions
- [ ] Add property-based tests with Hypothesis
- [ ] Set up continuous coverage monitoring

---

**Last Updated:** November 2025
**Maintained by:** RentIQ Team
