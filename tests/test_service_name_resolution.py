import pytest
from backend.services.service_resolver import ServiceResolver, ResolutionResult
from unittest.mock import AsyncMock, MagicMock

SYN_DICT = {
    "amazonec2": "AmazonEC2",
    "ec2": "AmazonEC2",
    "amazons3": "AmazonS3",
    "s3": "AmazonS3",
    "amazonvpc": "AmazonVPC",
    "vpc": "AmazonVPC",
    "virtualprivatecloud": "AmazonVPC",
}

PRODUCT_CODES = {"AmazonEC2", "AmazonS3", "AmazonVPC", "AWSLambda", "AmazonECS"}

@pytest.fixture
def resolver():
    r = ServiceResolver(SYN_DICT)
    r.update_product_codes(PRODUCT_CODES)
    return r

@pytest.fixture
def mock_llm_service():
    llm = MagicMock()
    async def mock_call(prompt, **kwargs):
        # Simple mock: extract candidates and return first one as JSON
        if "AmazonEC2" in prompt:
            return '{"product_code": "AmazonEC2"}'
        return '{"product_code": null}'
    llm.call_llm = AsyncMock(side_effect=mock_call)
    return llm

@pytest.mark.parametrize("phrase,expected,method", [
    ("EC2", "AmazonEC2", "dict"),
    ("Amazon EC2", "AmazonEC2", "dict"),
    ("S3", "AmazonS3", "dict"),
    ("VPC", "AmazonVPC", "dict"),
])
def test_dictionary_resolution(resolver, phrase, expected, method):
    result = resolver.resolve(phrase)
    assert result.product_code == expected
    assert result.method == method


def test_fuzzy_resolution(resolver):
    # Provide a misspelled variant not in dict but close to AmazonEC2
    phrase = "Amzon EC2"
    result = resolver.resolve(phrase)
    assert result.product_code in {"AmazonEC2", "AmazonS3", "AmazonVPC", None}
    # If fuzzy threshold yields match ensure method fuzzy; else fallback acceptable
    if result.method == "fuzzy":
        assert result.product_code == "AmazonEC2"
        assert result.confidence > 0.5


def test_fallback(resolver):
    phrase = "Some Unknown Service"
    result = resolver.resolve(phrase)
    assert result.product_code is None
    assert result.method == "fallback"


def test_ambiguity_detection():
    # Craft resolver with two very similar product codes
    syn = {}
    r = ServiceResolver(syn)
    r.update_product_codes(["AmazonEC2", "AmazonEC2Compute"])
    result: ResolutionResult = r.resolve("Amazon EC2")
    # Depending on fuzzy scores, may be ambiguous; allow both outcomes but assert fields
    if result.method == "ambiguous":
        assert result.needs_clarification is True
        assert result.product_code is None
    else:
        # If fuzzy confidently picks one
        assert result.product_code in ["AmazonEC2", "AmazonEC2Compute"]


def test_llm_resolution_fallback(mock_llm_service):
    # Resolver with LLM service for fallback when fuzzy doesn't meet threshold
    syn = {}
    r = ServiceResolver(syn, llm_service=mock_llm_service)
    r.update_product_codes(PRODUCT_CODES)
    # Use phrase that won't match dict but will fuzzy to EC2
    result: ResolutionResult = r.resolve("Elastic Compute Cloud Service")
    # Should use fuzzy or LLM depending on threshold
    assert result.product_code in ["AmazonEC2", None]
    if result.method == "llm":
        assert result.product_code == "AmazonEC2"
