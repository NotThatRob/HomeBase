import base64
import os


def main() -> None:
    print(base64.urlsafe_b64encode(os.urandom(32)).decode())


if __name__ == "__main__":
    main()
