#!/usr/bin/env python3
"""
SuperCAT Workbench – narzędzie CAT (Computer-Aided Translation).

Uruchomienie:
    python SuperCAT.py

Wymagania:
    pip install -r requirements.txt
"""
import sys

if __name__ == "__main__":
    from supercat.app import main

    sys.exit(main())
