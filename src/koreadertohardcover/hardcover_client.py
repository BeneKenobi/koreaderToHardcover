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

    def _execute_query(
        self, query: str, variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            try:
                response = client.post(
                    self.API_URL,
                    json={"query": query, "variables": variables or {}},
                    headers=self.headers,
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

    def get_me(self) -> Dict[str, Any]:
        """Fetches the authenticated user's information."""
        gql = """
        query GetMe {
          me {
            id
            username
            name
          }
        }
        """
        data = self._execute_query(gql)
        me = data.get("me", [])
        if me:
            return me[0]
        return {}

    def search_books(self, query: str) -> List[Dict[str, Any]]:
        gql = """
        query SearchBooks($query: String!) {
          search(query: $query) {
            results
          }
        }
        """
        data = self._execute_query(gql, {"query": query})

        results = []
        search_data = data.get("search", {})
        if not search_data:
            return []

        hits = search_data.get("results", {}).get("hits", [])
        for hit in hits:
            doc = hit.get("document", {})
            author_names = doc.get("author_names", [])
            author_name = author_names[0] if author_names else "Unknown"

            results.append(
                {
                    "id": doc["id"],
                    "title": doc["title"],
                    "author_name": author_name,
                    "pages": doc.get("pages"),
                    "slug": doc.get("slug"),
                }
            )
        return results

    def get_editions(self, book_id: int) -> List[Dict[str, Any]]:
        """Fetches editions for a given book ID."""
        gql = """
        query GetEditions($book_id: Int!) {
          editions(where: {book_id: {_eq: $book_id}}, order_by: {release_date: desc}) {
            id
            title
            pages
            edition_format
            release_date
            language {
              language
            }
          }
        }
        """
        data = self._execute_query(gql, {"book_id": book_id})
        results = []
        for ed in data.get("editions", []):
            lang_data = ed.get("language")
            language = lang_data.get("language") if lang_data else "Unknown"

            results.append(
                {
                    "id": ed["id"],
                    "title": ed["title"],
                    "pages": ed.get("pages"),
                    "edition_format": ed.get("edition_format"),
                    "release_date": ed.get("release_date"),
                    "language": language,
                }
            )
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
        """
        Searches the user's shelf for a book by title.
        First tries an exact API match. If that fails, fetches user's books
        and performs a local case-insensitive search.
        """
        # 1. Try exact API match
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

                results.append(
                    {
                        "id": book["id"],
                        "title": book["title"],
                        "author_name": author_name,
                        "pages": book.get("pages"),
                    }
                )

        if results:
            return results

        # 2. Fallback: Fetch all books and search locally
        print(f"  Exact match failed. Fetching shelf to search for '{title}'...")
        # Note: Limit 50 most recently updated books to find current reads
        gql_all = """
        query GetAllUserBooks {
          me {
            user_books(limit: 50, order_by: {updated_at: desc}) {
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
        data_all = self._execute_query(gql_all)
        me_all = data_all.get("me", [])

        if not me_all:
            return []

        search_term = title.lower().strip()

        for ub in me_all[0].get("user_books", []):
            book = ub["book"]
            book_title = book["title"]

            # Check for case-insensitive match
            if book_title.lower().strip() == search_term:
                author_name = "Unknown"
                if book.get("contributions"):
                    author_name = book["contributions"][0]["author"]["name"]

                results.append(
                    {
                        "id": book["id"],
                        "title": book_title,
                        "author_name": author_name,
                        "pages": book.get("pages"),
                    }
                )

        return results

    def update_progress(
        self,
        book_id: str,
        percentage: float,
        status: str,
        seconds: int = 0,
        last_read_date: Any = None,
        start_date: Any = None,
        force: bool = False,
        edition_id: Optional[str] = None,
    ) -> bool:
        """
        Updates the progress of a book on Hardcover.
        """
        status_id = 2 if status == "reading" else 3
        b_id = int(book_id)
        e_id = int(edition_id) if edition_id else None

        try:
            # 1. Get Book/Edition total pages
            total_pages = None
            if e_id:
                edition_gql = "query GetEditionPages($id: Int!) { editions_by_pk(id: $id) { pages } }"
                ed_res = self._execute_query(edition_gql, {"id": e_id})
                if ed_res.get("editions_by_pk"):
                    total_pages = ed_res["editions_by_pk"].get("pages")

            if not total_pages:
                book_gql = (
                    "query GetBookPages($id: Int!) { books_by_pk(id: $id) { pages } }"
                )
                bk_res = self._execute_query(book_gql, {"id": b_id})
                if bk_res.get("books_by_pk"):
                    total_pages = bk_res["books_by_pk"].get("pages")

            # 2. Get UserBook info
            ub_gql = """
            query GetUserBookInfo($book_id: Int!) {
              me {
                user_books(where: {book_id: {_eq: $book_id}}) {
                  id
                  status_id
                  edition_id
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
            info = self._execute_query(ub_gql, {"book_id": b_id})

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
            current_edition = user_book.get("edition_id") if user_book else None
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
            if (
                not force
                and user_book
                and current_status == status_id
                and (e_id is None or current_edition == e_id)
            ):
                page_match = (
                    current_page is not None and abs(current_page - target_page) < 2
                )
                time_match = (
                    current_seconds is not None
                    and abs((current_seconds or 0) - seconds) < 60
                )  # Allow 1 min drift

                # Date matches (comparing string YYYY-MM-DD)
                target_start = start_date.strftime("%Y-%m-%d") if start_date else None
                target_finish = (
                    last_read_date.strftime("%Y-%m-%d")
                    if (status == "finished" and last_read_date)
                    else None
                )

                start_match = current_start == target_start
                finish_match = (
                    (current_finish == target_finish) if status == "finished" else True
                )

                if page_match and time_match and start_match and finish_match:
                    print("  No changes needed (up to date).")
                    return True

            # 2. If no UserBook, create it
            if not user_book:
                create_ub_gql = """
                mutation CreateUserBook($book_id: Int!, $status_id: Int!, $edition_id: Int) {
                  insert_user_book(object: {book_id: $book_id, status_id: $status_id, edition_id: $edition_id}) {
                    id
                  }
                }
                """
                res = self._execute_query(
                    create_ub_gql,
                    {"book_id": b_id, "status_id": status_id, "edition_id": e_id},
                )
                ub_id = res["insert_user_book"]["id"]

                # Check if a read was auto-created by fetching the new user_book
                fetch_new_ub = """
                query GetNewUserBook($id: Int!) {
                  user_books_by_pk(id: $id) {
                    user_book_reads(order_by: {id: desc}, limit: 1) {
                      id
                    }
                  }
                }
                """
                new_ub_res = self._execute_query(fetch_new_ub, {"id": ub_id})
                new_ub_reads = new_ub_res.get("user_books_by_pk", {}).get(
                    "user_book_reads", []
                )
                ubr_id = new_ub_reads[0]["id"] if new_ub_reads else None

                # Since we just created it with these values, update current state to avoid redundant update in Step 6
                current_status = status_id
                current_edition = e_id
            else:
                ub_id = user_book["id"]
                ubr_list = user_book.get("user_book_reads", [])
                ubr_id = ubr_list[0]["id"] if ubr_list else None

            # 3. If no UserBookRead, create it
            if not ubr_id:
                create_ubr_gql = """
                mutation CreateUserBookRead($ub_id: Int!) {
                  insert_user_book_read(user_book_id: $ub_id, user_book_read: {}) {
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

            started_at_str = (
                start_date.strftime("%Y-%m-%d") if start_date else current_start
            )

            self._execute_query(
                update_ubr_gql,
                {
                    "ubr_id": ubr_id,
                    "pages": target_page if total_pages else current_page,
                    "seconds": seconds,
                    "started_at": started_at_str,
                    "finished_at": finished_at_str,
                },
            )

            # 6. Update Status and Edition (if changed)
            if current_status != status_id or current_edition != e_id:
                update_ub_gql = """
                mutation UpdateUB($ub_id: Int!, $status_id: Int!, $edition_id: Int) {
                  update_user_book(id: $ub_id, object: {status_id: $status_id, edition_id: $edition_id}) {
                    id
                  }
                }
                """
                self._execute_query(
                    update_ub_gql,
                    {"ub_id": ub_id, "status_id": status_id, "edition_id": e_id},
                )

            return True
        except Exception as e:
            print(f"Error updating progress: {e}")
            return False
