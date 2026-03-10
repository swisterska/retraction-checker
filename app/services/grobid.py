import requests

GROBID_URL = "http://localhost:8070/api/processReferences"


def parse_references(pdf_path: str) -> str:
    """
    Extract bibliographic references from a PDF using a local GROBID service.

    This function sends a PDF file to the GROBID 'processReferences' endpoint
    and returns the parsed references in TEI XML format.

    Parameters:
    pdf_path : str
        Path to the PDF file containing the document whose references should
        be extracted.

    Returns:
    str
        TEI XML string returned by the GROBID API containing the parsed
        reference list.

    Raises:
    requests.exceptions.HTTPError
        Raised if the HTTP request to the GROBID service returns an error
        status code.
    FileNotFoundError
        Raised if the provided PDF path does not exist.

    Notes:
    - Requires a running GROBID service at 'http://localhost:8070'.
    - Uses the '/api/processReferences' endpoint which extracts references
      from the bibliography section of the PDF.

    """
    
    with open(pdf_path, "rb") as pdf_file:
        files = {"input": pdf_file}

        response = requests.post(GROBID_URL, files=files)

    response.raise_for_status()

    return response.text