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
        fragment1 = b"1"
        fragment2 = b"0\r\n0123456789\r\n0\r\n\r\n"
        parser.feed(fragment1)
        self.assertFalse(parser.is_done)
        self.assertEqual(parser.state, ChunkedState.READ_SIZE)
        parser.feed(fragment2)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"0123456789")

    def test_hex_size_split_each_digit(self):
        parser = ChunkedParser()
        data = b"1A\r\n0123456789ABCDEF\r\n0\r\n\r\n"
        parser.feed(b"1")
        self.assertEqual(parser.state, ChunkedState.READ_SIZE)
        parser.feed(b"A")
        self.assertEqual(parser.state, ChunkedState.READ_SIZE)
        parser.feed(b"\r")
        self.assertEqual(parser.state, ChunkedState.EXPECT_SIZE_CRLF)
        parser.feed(b"\n")
        self.assertEqual(parser.state, ChunkedState.READ_DATA)
        parser.feed(b"0123456789ABCDEF")
        parser.feed(b"\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"0123456789ABCDEF")

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
        parser.feed(b"6789ABCDEF")
        self.assertEqual(parser.state, ChunkedState.READ_DATA)
        parser.feed(b"\r\n0\r\n\r\n")
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"0123456789ABCDEF")

    def test_everything_split(self):
        parser = ChunkedParser()
        chunks = [
            b"2",
            b"3",
            b"\r",
            b"\n",
            b"H",
            b"e",
            b"l",
            b"l",
            b"o",
            b" ",
            b"W",
            b"o",
            b"r",
            b"l",
            b"d",
            b"!",
            b"\r",
            b"\n",
            b"0",
            b"\r",
            b"\n",
            b"\r",
            b"\n",
        ]
        for i, chunk in enumerate(chunks):
            parser.feed(chunk)
            if i < len(chunks) - 1:
                self.assertFalse(parser.is_done)
        self.assertTrue(parser.is_done)
        self.assertEqual(parser.body, b"Hello World!")


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
    def test_huge_chunk_size_declaration(self):
        parser = ChunkedParser(max_chunk_size=1024)
        data = b"FFFFFFFF\r\n" + b"A" * 0xFFFFFFFF
        parser.feed(data)
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, ChunkSizeLimitExceeded)

    def test_0xffffffff_malicious_chunk(self):
        parser = ChunkedParser(max_chunk_size=1024 * 1024)
        data = b"FFFFFFFF\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, ChunkSizeLimitExceeded)

    def test_very_long_hex_digits(self):
        parser = ChunkedParser()
        data = b"123456789ABCDEF\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, ChunkSizeLimitExceeded)

    def test_total_size_limit(self):
        parser = ChunkedParser(max_chunk_size=1024, max_total_size=50)
        data = b"20\r\n" + b"A" * 32 + b"\r\n20\r\n" + b"B" * 32 + b"\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_error)
        self.assertIsInstance(parser.error, TotalSizeLimitExceeded)

    def test_buffer_overflow_in_size_state(self):
        parser = ChunkedParser(max_buffer_size=10)
        data = b"12345678901234567890"
        parser.feed(data)
        self.assertTrue(parser.is_error)

    def test_buffer_overflow_in_ext_state(self):
        parser = ChunkedParser(max_buffer_size=10)
        data = b"4;ext12345678901234567890"
        parser.feed(data)
        self.assertTrue(parser.is_error)

    def test_buffer_overflow_in_trailer_state(self):
        parser = ChunkedParser(max_buffer_size=10)
        data = b"0\r\nVeryLongTrailerHeader: value\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_error)

    def test_invalid_character_in_size(self):
        parser = ChunkedParser()
        data = b"G\r\ntest\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_error)

    def test_empty_chunk_size(self):
        parser = ChunkedParser()
        data = b"\r\ntest\r\n0\r\n\r\n"
        parser.feed(data)
        self.assertTrue(parser.is_error)

    def test_missing_crlf_after_data(self):
        parser = ChunkedParser()
        data = b"4\r\nWikiX\r\n0\r\n\r\n"
        parser.feed(data)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
