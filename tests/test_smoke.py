import re

import ec2_scraping


def test_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", ec2_scraping.__version__)
