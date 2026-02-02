# Sends the file, download the answer
import requests

GROBID_URL = "http://localhost:8070/api/processReferences"


def parse_references(pdf_path: str) -> str:
   
    """
    Sends PDF file to GROBID and returns XML with references.
    """

    with open(pdf_path, "rb") as pdf_file:
        files = {"input": pdf_file}

        response = requests.post(GROBID_URL, files=files) # Sends pdf to grobid

    response.raise_for_status() # Raise error if request failed

    return response.text
