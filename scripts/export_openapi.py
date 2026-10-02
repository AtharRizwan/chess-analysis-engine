"""Write the API's OpenAPI schema to stdout (used to generate the web app's TypeScript types)."""

import json

from chess_analysis_engine.api.app import create_app

if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), indent=1))
