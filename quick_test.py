from chunked_parser import (
    ChunkedParser,
    ChunkedState,
    ChunkSizeLimitExceeded,
    TotalSizeLimitExceeded,
)


def test_basic():
    print("=== 基本功能测试 ===")
    parser = ChunkedParser()
    data = b"4\r\nWiki\r\n0\r\n\r\n"
    parser.feed(data)
    assert parser.is_done, "应该解析完成"
    assert parser.body == b"Wiki", f"body应该是Wiki，实际是{parser.body}"
    print("  ✓ 单chunk解析正常")

    parser = ChunkedParser()
    data = b"5\r\nHello\r\n6\r\n World\r\n0\r\n\r\n"
    parser.feed(data)
    assert parser.is_done
    assert parser.body == b"Hello World"
    print("  ✓ 多chunk解析正常")

    parser = ChunkedParser()
    data = b"0\r\n\r\n"
    parser.feed(data)
    assert parser.is_done
    assert parser.body == b""
    print("  ✓ 空body解析正常")


def test_fragmented():
    print("\n=== 片段化测试 ===")

    parser = ChunkedParser()
    data = b"4\r\nWiki\r\n0\r\n\r\n"
    for b in data:
        parser.feed(bytes([b]))
    assert parser.is_done
    assert parser.body == b"Wiki"
    print("  ✓ 逐字节输入正常")

    parser = ChunkedParser()
    parser.feed(b"1")
    assert parser.state == ChunkedState.READ_SIZE
    parser.feed(b"0\r\n0123456789ABCDEF\r\n0\r\n\r\n")
    assert parser.is_done
    assert parser.body == b"0123456789ABCDEF"
    print("  ✓ 十六进制长度横跨片段正常")

    parser = ChunkedParser()
    parser.feed(b"4\r")
    assert parser.state == ChunkedState.EXPECT_SIZE_CRLF
    parser.feed(b"\nWiki\r\n0\r\n\r\n")
    assert parser.is_done
    assert parser.body == b"Wiki"
    print("  ✓ size后的CRLF被拆散正常")

    parser = ChunkedParser()
    parser.feed(b"4\r\nWiki\r")
    assert parser.state == ChunkedState.EXPECT_DATA_CRLF
    parser.feed(b"\n0\r\n\r\n")
    assert parser.is_done
    assert parser.body == b"Wiki"
    print("  ✓ data后的CRLF被拆散正常")

    parser = ChunkedParser()
    parser.feed(b"10\r\n012345")
    assert parser.state == ChunkedState.READ_DATA
    parser.feed(b"6789ABCDEF\r\n0\r\n\r\n")
    assert parser.is_done
    assert parser.body == b"0123456789ABCDEF"
    print("  ✓ chunk数据横跨多片段正常")


def test_security():
    print("\n=== 安全性测试 ===")

    parser = ChunkedParser(max_chunk_size=1024)
    parser.feed(b"FFFFFFFF\r\n")
    assert parser.is_error
    assert isinstance(parser.error, ChunkSizeLimitExceeded)
    print("  ✓ 0xFFFFFFFF恶意chunk被拦截")

    parser = ChunkedParser(max_chunk_size=1024, max_total_size=50)
    data = b"20\r\n" + b"A" * 32 + b"\r\n20\r\n" + b"B" * 32 + b"\r\n0\r\n\r\n"
    parser.feed(data)
    assert parser.is_error
    assert isinstance(parser.error, TotalSizeLimitExceeded)
    print("  ✓ 总数据量超限被拦截")

    parser = ChunkedParser(max_buffer_size=10)
    parser.feed(b"12345678901234567890")
    assert parser.is_error
    print("  ✓ 缓冲区溢出保护生效")

    parser = ChunkedParser()
    parser.feed(b"123456789ABCDEF\r\n")
    assert parser.is_error
    assert isinstance(parser.error, ChunkSizeLimitExceeded)
    print("  ✓ 超长十六进制数字符串被拦截")


def test_extensions_and_trailers():
    print("\n=== 扩展和尾部测试 ===")

    parser = ChunkedParser()
    data = b"4;name=value\r\nWiki\r\n0\r\n\r\n"
    parser.feed(data)
    assert parser.is_done
    assert parser.body == b"Wiki"
    print("  ✓ chunk扩展解析正常")

    parser = ChunkedParser()
    data = b"4\r\nWiki\r\n0\r\nTrailer: value\r\n\r\n"
    parser.feed(data)
    assert parser.is_done
    assert parser.body == b"Wiki"
    assert parser.trailers["trailer"] == "value"
    print("  ✓ trailer解析正常")


def main():
    try:
        test_basic()
        test_fragmented()
        test_security()
        test_extensions_and_trailers()
        print("\n" + "=" * 50)
        print("所有测试通过! ✓")
        print("=" * 50)
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ 异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
