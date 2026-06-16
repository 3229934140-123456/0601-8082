from enum import Enum, auto
from typing import Optional, List, Tuple


class ChunkedState(Enum):
    READ_SIZE = auto()
    READ_EXT = auto()
    EXPECT_SIZE_CRLF = auto()
    READ_DATA = auto()
    EXPECT_DATA_CRLF = auto()
    READ_TRAILER = auto()
    DONE = auto()
    ERROR = auto()


class ChunkedParserError(Exception):
    pass


class ChunkSizeLimitExceeded(ChunkedParserError):
    pass


class TotalSizeLimitExceeded(ChunkedParserError):
    pass


class ChunkedParser:
    DEFAULT_MAX_CHUNK_SIZE = 1024 * 1024 * 16
    DEFAULT_MAX_TOTAL_SIZE = 1024 * 1024 * 64
    DEFAULT_MAX_BUFFER_SIZE = 4096

    def __init__(
        self,
        max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
        max_total_size: int = DEFAULT_MAX_TOTAL_SIZE,
        max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE,
    ):
        self.state = ChunkedState.READ_SIZE
        self.buffer = bytearray()
        self.current_chunk_size = 0
        self.chunk_ext = b""
        self.total_bytes_consumed = 0
        self.trailers = {}
        self._max_chunk_size = max_chunk_size
        self._max_total_size = max_total_size
        self._max_buffer_size = max_buffer_size
        self._current_trailer_line = b""
        self._chunks: List[bytes] = []

    @property
    def is_done(self) -> bool:
        return self.state == ChunkedState.DONE

    @property
    def is_error(self) -> bool:
        return self.state == ChunkedState.ERROR

    @property
    def chunks(self) -> List[bytes]:
        return list(self._chunks)

    @property
    def body(self) -> bytes:
        return b"".join(self._chunks)

    def feed(self, data: bytes) -> None:
        if self.state == ChunkedState.DONE or self.state == ChunkedState.ERROR:
            return

        if not data:
            return

        self.buffer.extend(data)

        if len(self.buffer) > self._max_buffer_size and self.state in (
            ChunkedState.READ_SIZE,
            ChunkedState.READ_EXT,
            ChunkedState.EXPECT_SIZE_CRLF,
            ChunkedState.READ_TRAILER,
        ):
            self._set_error(ChunkedParserError("Buffer overflow in header parsing state"))
            return

        self._process_buffer()

    def _process_buffer(self) -> None:
        while self.state not in (ChunkedState.DONE, ChunkedState.ERROR) and self.buffer:
            prev_state = self.state
            prev_buffer_len = len(self.buffer)

            if self.state == ChunkedState.READ_SIZE:
                self._parse_size()
            elif self.state == ChunkedState.READ_EXT:
                self._parse_ext()
            elif self.state == ChunkedState.EXPECT_SIZE_CRLF:
                self._expect_size_crlf()
            elif self.state == ChunkedState.READ_DATA:
                self._parse_data()
            elif self.state == ChunkedState.EXPECT_DATA_CRLF:
                self._expect_data_crlf()
            elif self.state == ChunkedState.READ_TRAILER:
                self._parse_trailer()
            else:
                break

            if self.state == prev_state and len(self.buffer) == prev_buffer_len:
                break

    def _parse_size(self) -> None:
        size_str = bytearray()
        i = 0
        while i < len(self.buffer):
            b = self.buffer[i]
            if b == ord(b"\r"):
                if i == 0:
                    self._set_error(ChunkedParserError("Empty chunk size"))
                    return
                self.state = ChunkedState.EXPECT_SIZE_CRLF
                self.buffer = self.buffer[i:]
                self._parse_size_value(bytes(size_str))
                return
            elif b == ord(b";"):
                if i == 0:
                    self._set_error(ChunkedParserError("Empty chunk size before extension"))
                    return
                self.state = ChunkedState.READ_EXT
                self.buffer = self.buffer[i + 1:]
                self._parse_size_value(bytes(size_str))
                return
            elif self._is_hex_digit(b):
                if len(size_str) > 8:
                    self._set_error(ChunkSizeLimitExceeded(
                        f"Chunk size hex string too long: {len(size_str)} digits"
                    ))
                    return
                size_str.append(b)
                i += 1
            else:
                self._set_error(ChunkedParserError(
                    f"Invalid character in chunk size: {chr(b) if b < 128 else '0x%02x' % b}"
                ))
                return

    def _parse_size_value(self, size_str: bytes) -> None:
        try:
            size = int(size_str, 16)
        except ValueError:
            self._set_error(ChunkedParserError(f"Invalid chunk size hex: {size_str!r}"))
            return

        if size > self._max_chunk_size:
            self._set_error(ChunkSizeLimitExceeded(
                f"Chunk size {size} exceeds limit {self._max_chunk_size}"
            ))
            return

        self.current_chunk_size = size

    def _parse_ext(self) -> None:
        ext_bytes = bytearray()
        i = 0
        while i < len(self.buffer):
            b = self.buffer[i]
            if b == ord(b"\r"):
                self.chunk_ext += bytes(ext_bytes)
                self.state = ChunkedState.EXPECT_SIZE_CRLF
                self.buffer = self.buffer[i:]
                return
            ext_bytes.append(b)
            i += 1

    def _expect_size_crlf(self) -> None:
        if len(self.buffer) < 2:
            return

        if self.buffer[0] == ord(b"\r") and self.buffer[1] == ord(b"\n"):
            del self.buffer[:2]

            if self.current_chunk_size == 0:
                self.state = ChunkedState.READ_TRAILER
                self._current_trailer_line = b""
            else:
                if self.total_bytes_consumed + self.current_chunk_size > self._max_total_size:
                    self._set_error(TotalSizeLimitExceeded(
                        f"Total size would exceed limit: "
                        f"{self.total_bytes_consumed + self.current_chunk_size} > {self._max_total_size}"
                    ))
                    return
                self.state = ChunkedState.READ_DATA
        else:
            self._set_error(ChunkedParserError("Expected CRLF after chunk size"))

    def _parse_data(self) -> None:
        if self.current_chunk_size == 0:
            self.state = ChunkedState.EXPECT_DATA_CRLF
            return

        available = len(self.buffer)
        if available == 0:
            return

        take = min(available, self.current_chunk_size)
        chunk_data = bytes(self.buffer[:take])
        self._chunks.append(chunk_data)
        self.total_bytes_consumed += take
        del self.buffer[:take]
        self.current_chunk_size -= take

        if self.current_chunk_size == 0:
            self.state = ChunkedState.EXPECT_DATA_CRLF

    def _expect_data_crlf(self) -> None:
        if len(self.buffer) < 2:
            return

        if self.buffer[0] == ord(b"\r") and self.buffer[1] == ord(b"\n"):
            del self.buffer[:2]
            self.state = ChunkedState.READ_SIZE
            self.chunk_ext = b""
        else:
            self._set_error(ChunkedParserError("Expected CRLF after chunk data"))

    def _parse_trailer(self) -> None:
        i = 0
        while i < len(self.buffer):
            b = self.buffer[i]
            if b == ord(b"\r"):
                line = self._current_trailer_line
                self._current_trailer_line = b""
                rest = self.buffer[i:]
                if len(rest) < 2:
                    return
                if rest[1] != ord(b"\n"):
                    self._set_error(ChunkedParserError("Malformed trailer line ending"))
                    return
                del self.buffer[:i + 2]

                if line == b"":
                    self.state = ChunkedState.DONE
                else:
                    self._parse_trailer_line(line)
                return
            else:
                self._current_trailer_line += bytes([b])
                if len(self._current_trailer_line) > self._max_buffer_size:
                    self._set_error(ChunkedParserError("Trailer line too long"))
                    return
                i += 1

    def _parse_trailer_line(self, line: bytes) -> None:
        try:
            line_str = line.decode("ascii")
        except UnicodeDecodeError:
            self._set_error(ChunkedParserError("Non-ASCII trailer header"))
            return

        if ":" in line_str:
            name, value = line_str.split(":", 1)
            self.trailers[name.strip().lower()] = value.strip()

    def _set_error(self, error: Exception) -> None:
        self.state = ChunkedState.ERROR
        self._error = error

    @property
    def error(self) -> Optional[Exception]:
        if hasattr(self, "_error"):
            return self._error
        return None

    @staticmethod
    def _is_hex_digit(b: int) -> bool:
        return (
            (ord(b"0") <= b <= ord(b"9"))
            or (ord(b"A") <= b <= ord(b"F"))
            or (ord(b"a") <= b <= ord(b"f"))
        )
