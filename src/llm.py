"""
Client OpenAI partagé.

La clé est facultative : sans OPENAI_API_KEY, client vaut None et les
fonctions qui appellent le LLM (relecture sémantique, noms de colonnes,
instructions, synthèse, demande en langage naturel) se déclarent
indisponibles ; tout le reste du workflow fonctionne.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def create_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=api_key) if api_key else None


client = create_client()
