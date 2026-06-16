import unittest
from chunked_parser import (
    ChunkedParser,
    ChunkedState,
    ChunkedParserError,
    ChunkSizeLimitExceeded,
    TotalSizeLimitExceeded,
)


class TestChunkedParserBasic(unittest.TestCase):
    def test_single_chunk(self):
        parser = ChunkedParser()
        data = b"4\r\nWiki\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Wiki")

    def test_multiple_chunks(self):
        parser = ChunkedParser()
        data = b"5\r\nHello\r\n6\r\n World\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Hello World")

    def test_empty_body(self):
        parser = ChunkedParser()
        data = b"0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"")

    def test_uppercase_hex(self):
        parser = ChunkedParser()
        data = b"A\r\n0123456789\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"0123456789")

    def test_lowercase_hex(self):
        parser = ChunkedParser()
        data = b"a\r\n0123456789\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"0123456789")


class TestChunkedParserFragmented(unittest.TestCase):
    def test_byte_by_byte(self):
        parser = ChunkedParser()
        data = b"4\r\nWiki\r\n0\r\n\r\n"
        for b in data:
            parser.feed(bytes([b]))
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Wiki")

    def test_hex_size_split_across_fragments(self):
        parser = ChunkedParser()
        fragment1 = b"A"
        fragment2 = b"\r\n0123456789\r\n0\r\n\r\n"
        parser.feed(fragment1)
        self.assertFalse(parser.is_done)
        self.assertEqual(parser.state, ChunkedState.READ_SIZE)
        parser.feed(fragment2)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"0123456789")

    def test_hex_size_split_each_digit(self):
        parser = ChunkedParser()
        body = b"0123456789ABCDEF"
        data = f"{len(body):X}\r\n".encode() + body + b"\r\n0\r\n\r\n"
        parser.feed(b"1")
        self.assertEqual(parser.state, ChunkedState.READ_SIZE)
        parser.feed(b"0")
        self.assertEqual(parser.state, ChunkedState.READ_SIZE)
        parser.feed(b"\r")
        self.assertEqual(parser.state, ChunkedState.EXPECT_SIZE_CRLF)
        parser.feed(b"\n")
        self.assertEqual(parser.state, ChunkedState.READ_DATA)
        parser.feed(body)
        parser.feed(b"\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, body)

    def test_crlf_after_size_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r")
        self.assertEqual(parser.state, ChunkedState.EXPECT_SIZE_CRLF)
        parser.feed(b"\nWiki\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Wiki")

    def test_crlf_after_data_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r")
        self.assertEqual(parser.state, ChunkedState.EXPECT_DATA_CRLF)
        parser.feed(b"\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Wiki")

    def test_data_split_across_fragments(self):
        parser = ChunkedParser()
        parser.feed(b"10\r\n012345")
        self.assertEqual(parser.state, ChunkedState.READ_DATA)
        self.assertEqual(parser.current_chunk_size, 10)
        parser.feed(b"6789ABCDEF")
        self.assertEqual(parser.state, ChunkedState.EXPECT_DATA_CRLF)
        self.assertEqual(parser.current_chunk_size, 0)
        parser.feed(b"\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"0123456789ABCDEF")

    def test_everything_split(self):
        parser = ChunkedParser()
        body = b"Hello World!"
        size_hex = f"{len(body):X}".encode()
        chunks = []
        for byte in size_hex:
            chunks.append(bytes([byte]))
        chunks.extend([
            b"\r",
            b"\n",
        ])
        for byte in body:
            chunks.append(bytes([byte]))
        chunks.extend([
            b"\r",
            b"\n",
            b"0",
            b"\r",
            b"\n",
            b"\r",
            b"\n",
        ])
        for i, chunk in enumerate(chunks):
            parser.feed(chunk)
            if i < len(chunks) - 1:
                self.assertFalse(parser.is_done)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, body)


class TestChunkedParserExtensions(unittest.TestCase):
    def test_chunk_extension(self):
        parser = ChunkedParser()
        data = b"4;name=value\r\nWiki\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Wiki")

    def test_chunk_extension_split(self):
        parser = ChunkedParser()
        parser.feed(b"4;ext")
        self.assertEqual(parser.state, ChunkedState.READ_EXT)
        parser.feed(b"\r\ndata\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"data")

    def test_chunk_extension_split_across_fragments(self):
        parser = ChunkedParser()
        parser.feed(b"4;foo=bar;baz")
        self.assertEqual(parser.state, ChunkedState.READ_EXT)
        parser.feed(b"=qux\r\ntest\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"test")


class TestChunkedParserTrailers(unittest.TestCase):
    def test_trailer_header(self):
        parser = ChunkedParser()
        data = b"4\r\nWiki\r\n0\r\nTrailer: value\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Wiki")
        self.assertEqual(parser.trailers["trailer"], "value")

    def test_multiple_trailers(self):
        parser = ChunkedParser()
        data = (
            b"4\r\nWiki\r\n0\r\n"
            b"Trailer1: value1\r\n"
            b"Trailer2: value2\r\n"
            b"\r\n"
        )
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.trailers["trailer1"], "value1")
        self.assertEqual(parser.trailers["trailer2"], "value2")

    def test_trailer_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r\n0\r\nTrail")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"er: test\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.trailers["trailer"], "test")

    def test_trailer_crlf_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r\n0\r\nTrailer: test\r")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"\n\r\n")
        self.assertTrue(parser.is_done)


class TestChunkedParserSecurity(unittest.TestCase):
    def test_0xffffffff_malicious_chunk_declaration_only(self):
        parser = ChunkedParser(max_chunk_size=1024)
        parser.feed(b"FFFFFFFF\r\n")
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, ChunkSizeLimitExceeded)

    def test_0xffffffff_malicious_chunk(self):
        parser = ChunkedParser(max_chunk_size=1024 * 1024)
        parser.feed(b"FFFFFFFF\r\n")
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, ChunkSizeLimitExceeded)

    def test_very_long_hex_digits(self):
        parser = ChunkedParser()
        parser.feed(b"123456789ABCDEF\r\n")
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, ChunkSizeLimitExceeded)

    def test_total_size_limit(self):
        parser = ChunkedParser(max_chunk_size=1024, max_total_size=50)
        data = b"20\r\n" + b"A" * 32 + b"\r\n20\r\n" + b"B" * 32 + b"\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, TotalSizeLimitExceeded)

    def test_long_hex_digits_trigger_size_limit(self):
        parser = ChunkedParser()
        parser.feed(b"1234567890")
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, ChunkSizeLimitExceeded)

    def test_buffer_overflow_in_ext_state(self):
        parser = ChunkedParser(max_buffer_size=10)
        parser.feed(b"4;ext12345678901234567890")
        self.assertTrue(parser.is_error)

    def test_buffer_overflow_in_trailer_state(self):
        parser = ChunkedParser(max_buffer_size=10)
        parser.feed(b"0\r\nVeryLongTrailerHeader: value\r\n\r\n")
        self.assertTrue(parser.is_error)

    def test_invalid_character_in_size(self):
        parser = ChunkedParser()
        parser.feed(b"G\r\ntest\r\n0\r\n\r\n")
        self.assertTrue(parser.is_error)

    def test_empty_chunk_size(self):
        parser = ChunkedParser()
        parser.feed(b"\r\ntest\r\n0\r\n\r\n")
        self.assertTrue(parser.is_error)

    def test_missing_crlf_after_data(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWikiX\r\n0\r\n\r\n")
        self.assertTrue(parser.is_error)


class TestChunkedParserEdgeCases(unittest.TestCase):
    def test_zero_size_chunk_not_last(self):
        parser = ChunkedParser()
        data = b"0\r\n4\r\nWiki\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)

    def test_large_but_valid_chunk(self):
        parser = ChunkedParser(max_chunk_size=1024 * 1024)
        size = 1000
        data = f"{size:X}\r\n".encode() + b"A" * size + b"\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_done)
        self.assertEqual(len(parser.body), size)

    def test_single_feed_large_chunk_exceeds_default_header_buffer(self):
        default_header_buffer = 4096
        body_size = default_header_buffer + 1024
        parser = ChunkedParser(
            max_chunk_size=body_size + 1000,
            max_total_size=body_size + 1000,
        )
        header = f"{body_size:X}\r\n".encode()
        body = b"X" * body_size
        trailer = b"\r\n0\r\n\r\n"
        full_data = header + body + trailer
        parser.feed(full_data)
        self.assertTrue(parser.is_done, f"解析失败: state={parser.state}, error={parser.error}")
        self.assertEqual(len(parser.body), body_size)
        self.assertEqual(parser.body[:5], b"XXXXX")
        self.assertEqual(parser.body[-5:], b"XXXXX")

    def test_single_feed_10kb_chunk(self):
        body_size = 10 * 1024
        parser = ChunkedParser(
            max_chunk_size=1024 * 1024,
            max_total_size=1024 * 1024,
        )
        header = f"{body_size:X}\r\n".encode()
        body = bytes([i % 256 for i in range(body_size)])
        trailer = b"\r\n0\r\n\r\n"
        full_data = header + body + trailer
        parser.feed(full_data)
        self.assertTrue(parser.is_done, f"解析失败: state={parser.state}, error={parser.error}")
        self.assertEqual(len(parser.body), body_size)

    def test_feed_after_done(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        parser.feed(b"extra data")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Wiki")

    def test_feed_after_error(self):
        parser = ChunkedParser(max_chunk_size=10)
        parser.feed(b"FFFFFFFF\r\n")
        self.assertTrue(parser.is_error)
        parser.feed(b"more data")
        self.assertTrue(parser.is_error)

    def test_empty_feed(self):
        parser = ChunkedParser()
        parser.feed(b"")
        self.assertEqual(parser.state, ChunkedState.READ_SIZE)

    def test_chunks_property(self):
        parser = ChunkedParser()
        data = b"5\r\nHello\r\n6\r\n World\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertEqual(len(parser.chunks), 2)
        self.assertEqual(parser.chunks[0], b"Hello")
        self.assertEqual(parser.chunks[1], b" World")


class TestChunkedParserTrailerSplitEdgeCases(unittest.TestCase):
    def test_trailer_value_and_crlf_completely_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r\n0\r\nTrailer: value")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"\r")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"\n")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"\r")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.trailers["trailer"], "value")
        self.assertEqual(parser.body, b"Wiki")

    def test_trailer_value_split_then_crlf_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r\n0\r\nTra")
        parser.feed(b"iler: test")
        parser.feed(b"\r")
        parser.feed(b"\n")
        parser.feed(b"\r")
        parser.feed(b"\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.trailers["trailer"], "test")
        self.assertEqual(parser.body, b"Wiki")

    def test_multiple_trailers_all_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r\n0\r\n")
        parser.feed(b"X-One: 1")
        parser.feed(b"\r")
        parser.feed(b"\n")
        parser.feed(b"X-Two: 2")
        parser.feed(b"\r")
        parser.feed(b"\n")
        parser.feed(b"\r")
        parser.feed(b"\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.trailers["x-one"], "1")
        self.assertEqual(parser.trailers["x-two"], "2")

    def test_final_empty_trailer_line_split(self):
        parser = ChunkedParser()
        parser.feed(b"4\r\nWiki\r\n0\r\nSome: thing\r\n")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"\r")
        self.assertEqual(parser.state, ChunkedState.READ_TRAILER)
        parser.feed(b"\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.trailers["some"], "thing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
