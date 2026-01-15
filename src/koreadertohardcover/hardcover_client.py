import httpx
from typing import List, Dict, Any, Optional
from koreadertohardcover.config import Config

class HardcoverClient:
    API_URL = "https://api.hardcover.app/v1/graphql"

    def __init__(self, config: Config):
        self.config = config
        if not config.HARDCOVER_BEARER_TOKEN:
            raise ValueError("HARDCOVER_BEARER_TOKEN is not set")
        
        self.headers = {
            "Authorization": f"Bearer {config.HARDCOVER_BEARER_TOKEN}",
            "Content-Type": "application/json",
        }

    def _execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with httpx.Client() as client:
            response = client.post(
                self.API_URL,
                json={"query": query, "variables": variables or {}},
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            if "errors" in data:
                raise RuntimeError(f"GraphQL Error: {data['errors']}")
            return data["data"]

    def search_books(self, query: str) -> List[Dict[str, Any]]:
        gql = """
        query SearchBooks($query: String!) {
          books(where: {title: {_ilike: $query}}, limit: 10) {
            id
            title
            author_name
          }
        }
        """
        # Add wildcards for partial matching if not already there
        if not query.startswith("%"):
            query = f"%{query}%"
            
        data = self._execute_query(gql, {"query": query})
        return data.get("books", [])

    def update_progress(self, book_id: str, percentage: float, status: str) -> bool:
        """
        Updates the progress of a book.
        Status should be 'reading' or 'finished'.
        """
        # Map local status to Hardcover status ID or slug
        # On Hardcover: 2 is 'Currently Reading', 3 is 'Read' (common IDs)
        # We'll use the 'upsert_user_book' pattern if available or a specific progress mutation
        
        status_id = 2 if status == "reading" else 3
        
        gql = """
        mutation UpdateProgress($book_id: Int!, $status_id: Int!, $progress: Int!) {
          insert_user_book_one(
            object: {
              book_id: $book_id,
              status_id: $status_id,
              progress_percent: $progress
            },
            on_conflict: {
              constraint: user_book_user_id_book_id_key,
              update_columns: [status_id, progress_percent]
            }
          ) {
            id
          }
        }
        """
        # Note: book_id in mutation might need to be Int or String depending on schema
        try:
            self._execute_query(gql, {
                "book_id": int(book_id),
                "status_id": status_id,
                "progress": int(percentage)
            })
            return True
        except Exception as e:
            # Fallback or log error
            print(f"Error updating progress: {e}")
            return False
