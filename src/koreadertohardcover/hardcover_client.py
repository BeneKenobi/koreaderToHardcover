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
            "Authorization": config.HARDCOVER_BEARER_TOKEN,
            "Content-Type": "application/json",
            "User-Agent": "curl/7.64.1",
        }

    def _execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with httpx.Client() as client:
            try:
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
            except httpx.HTTPStatusError as e:
                print(f"HTTP Error: {e.response.status_code}")
                print(f"Response: {e.response.text}")
                raise e

    def search_books(self, query: str) -> List[Dict[str, Any]]:
        gql = """
        query SearchBooks($query: String!) {
          books(where: {title: {_eq: $query}}, limit: 10) {
            id
            title
            pages
            canonical_id
            contributions {
              author {
                name
              }
            }
          }
        }
        """
        data = self._execute_query(gql, {"query": query})
        
        results = []
        for book in data.get("books", []):
            author_name = "Unknown"
            if book.get("contributions"):
                author_name = book["contributions"][0]["author"]["name"]
            
            results.append({
                "id": book["id"],
                "title": book["title"],
                "author_name": author_name,
                "pages": book.get("pages"),
                "canonical_id": book.get("canonical_id")
            })
        return results

    def is_book_on_shelf(self, book_id: int) -> bool:
        """Checks if a book ID is already on the user's shelf."""
        gql = """
        query IsBookOnShelf($book_id: Int!) {
          me {
            user_books(where: {book_id: {_eq: $book_id}}) {
              id
            }
          }
        }
        """
        data = self._execute_query(gql, {"book_id": book_id})
        me = data.get("me", [])
        if me and me[0].get("user_books"):
            return True
        return False

    def search_shelf(self, title: str) -> List[Dict[str, Any]]:
        """Searches the user's shelf for a book by title."""
        gql = """
        query SearchShelf($title: String!) {
          me {
            user_books(where: {book: {title: {_eq: $title}}}) {
              book {
                id
                title
                pages
                contributions {
                  author {
                    name
                  }
                }
              }
            }
          }
        }
        """
        data = self._execute_query(gql, {"title": title})
        
        results = []
        me_data = data.get("me")
        if me_data and len(me_data) > 0:
            for ub in me_data[0].get("user_books", []):
                book = ub["book"]
                author_name = "Unknown"
                if book.get("contributions"):
                    author_name = book["contributions"][0]["author"]["name"]
                
                results.append({
                    "id": book["id"],
                    "title": book["title"],
                    "author_name": author_name,
                    "pages": book.get("pages")
                })
        return results

    def update_progress(self, book_id: str, percentage: float, status: str, seconds: int = 0, last_read_date: Any = None, start_date: Any = None, force: bool = False) -> bool:
        """
        Updates the progress of a book on Hardcover.
        """
        status_id = 2 if status == "reading" else 3
        b_id = int(book_id)

        try:
            # 1. Get UserBook info and Book total pages
            info_gql = """
            query GetUserBookInfo($book_id: Int!) {
              books_by_pk(id: $book_id) {
                pages
              }
              me {
                user_books(where: {book_id: {_eq: $book_id}}) {
                  id
                  status_id
                  user_book_reads(order_by: {id: desc}, limit: 1) {
                    id
                    progress_pages
                    progress_seconds
                    started_at
                    finished_at
                  }
                }
              }
            }
            """
            info = self._execute_query(info_gql, {"book_id": b_id})
            
            book_data = info.get("books_by_pk")
            total_pages = book_data.get("pages") if book_data else None
            
            me_data = info.get("me", [])
            user_book = None
            if me_data and me_data[0].get("user_books"):
                user_book = me_data[0]["user_books"][0]

            # Calculate target page
            target_page = 0
            if total_pages and total_pages > 0:
                target_page = int(total_pages * percentage / 100)

            # Check if update is needed
            current_status = user_book.get("status_id") if user_book else None
            current_page = None
            current_seconds = None
            current_start = None
            current_finish = None
            if user_book:
                ubr_list = user_book.get("user_book_reads", [])
                if ubr_list:
                    current_page = ubr_list[0].get("progress_pages")
                    current_seconds = ubr_list[0].get("progress_seconds")
                    current_start = ubr_list[0].get("started_at")
                    current_finish = ubr_list[0].get("finished_at")
            
            # Skip if status, page, seconds and dates match (allow small drift), unless forced
            if not force and user_book and current_status == status_id:
                page_match = current_page is not None and abs(current_page - target_page) < 2
                time_match = current_seconds is not None and abs((current_seconds or 0) - seconds) < 60 # Allow 1 min drift
                
                # Date matches (comparing string YYYY-MM-DD)
                target_start = start_date.strftime("%Y-%m-%d") if start_date else None
                target_finish = last_read_date.strftime("%Y-%m-%d") if (status == "finished" and last_read_date) else None
                
                start_match = (current_start == target_start)
                finish_match = (current_finish == target_finish) if status == "finished" else True
                
                if page_match and time_match and start_match and finish_match:
                    print("  No changes needed (up to date).")
                    return True

            # 2. If no UserBook, create it
            if not user_book:
                create_ub_gql = """
                mutation CreateUserBook($book_id: Int!, $status_id: Int!) {
                  insert_user_book(object: {book_id: $book_id, status_id: $status_id}) {
                    id
                  }
                }
                """
                res = self._execute_query(create_ub_gql, {"book_id": b_id, "status_id": status_id})
                ub_id = res["insert_user_book"]["id"]
                ubr_id = None
            else:
                ub_id = user_book["id"]
                ubr_list = user_book.get("user_book_reads", [])
                ubr_id = ubr_list[0]["id"] if ubr_list else None

            # 3. If no UserBookRead, create it
            if not ubr_id:
                create_ubr_gql = """
                mutation CreateUserBookRead($ub_id: Int!) {
                  insert_user_book_read(object: {user_book_id: $ub_id}) {
                    id
                  }
                }
                """
                res = self._execute_query(create_ubr_gql, {"ub_id": ub_id})
                ubr_id = res["insert_user_book_read"]["id"]

            # 4. Update Progress (Pages & Seconds & Dates)
            update_ubr_gql = """
            mutation UpdateUBR($ubr_id: Int!, $pages: Int, $seconds: Int, $started_at: date, $finished_at: date) {
              update_user_book_read(id: $ubr_id, object: {
                progress_pages: $pages, 
                progress_seconds: $seconds, 
                started_at: $started_at,
                finished_at: $finished_at
              }) {
                id
              }
            }
            """
            
            finished_at_str = None
            if status == "finished" and last_read_date:
                finished_at_str = last_read_date.strftime("%Y-%m-%d")
            
            started_at_str = start_date.strftime("%Y-%m-%d") if start_date else current_start

            self._execute_query(update_ubr_gql, {
                "ubr_id": ubr_id, 
                "pages": target_page if total_pages else current_page,
                "seconds": seconds,
                "started_at": started_at_str,
                "finished_at": finished_at_str
            })

            # 6. Update Status (if changed)
            if current_status != status_id:
                update_ub_gql = """
                mutation UpdateUB($ub_id: Int!, $status_id: Int!) {
                  update_user_book(id: $ub_id, object: {status_id: $status_id}) {
                    id
                  }
                }
                """
                self._execute_query(update_ub_gql, {"ub_id": ub_id, "status_id": status_id})

            return True
        except Exception as e:
            print(f"Error updating progress: {e}")
            return False
