# SPDX-License-Identifier: Apache-2.0
import asyncio
import unittest
import test_dispatch
from aegisflow_dr.advisory.stream import stream_adapter, UsageFrame
from aegisflow_dr.advisory.dispatch import AdapterRequest, dispatch
from aegisflow_dr.advisory.contracts import AdvisoryError, MAX_BYTES
from aegisflow_dr.storage.store import canonical


class StreamTests(unittest.TestCase):
    setUp = test_dispatch.DispatchTests.setUp
    response = test_dispatch.DispatchTests.response

    def invoke(self, factory):
        return dispatch(self.prepared,self.quote,self.ledger,stream_adapter(self.quote.adapter_id,factory),
                        attempt_key='stream',deadline_ms=2000)

    def test_chunked_success_closes_and_preserves_exact_input(self):
        closed=[]
        async def source(request):
            try:
                self.assertEqual(request.messages,canonical(self.prepared.messages))
                body=self.response()
                yield body[:10]
                yield body[10:]
                yield UsageFrame(10,3)
            finally:closed.append(True)
        result=self.invoke(source)
        self.assertEqual(result['review']['status'],'VERIFIED_ADVISORY')
        self.assertEqual(closed,[True])
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],13)

    def test_timeout_cancels_and_closes_source_and_retains_hold(self):
        self.now=1990
        closed=[]
        async def source(request):
            try:
                await asyncio.sleep(1)
                yield b'x'
            finally:closed.append(True)
        self.assertEqual(self.invoke(source)['status'],'USAGE_UNKNOWN')
        self.assertEqual(closed,[True])
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_cancellation_propagates_and_closes_source(self):
        closed=[]
        async def source(request):
            try:
                raise asyncio.CancelledError()
                yield b'x'
            finally:closed.append(True)
        with self.assertRaises(asyncio.CancelledError):self.invoke(source)
        self.assertEqual(closed,[True])
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def assert_bad_frames(self, frames):
        closed=[]
        async def source(request):
            try:
                for frame in frames:yield frame
            finally:closed.append(True)
        self.assertEqual(self.invoke(source)['status'],'USAGE_UNKNOWN')
        self.assertEqual(closed,[True])
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_oversized_single_chunk_rejected(self):self.assert_bad_frames([b'x'*(MAX_BYTES+1)])
    def test_cumulative_byte_overflow_rejected(self):self.assert_bad_frames([b'x'*MAX_BYTES,b'y'])
    def test_empty_chunk_rejected(self):self.assert_bad_frames([b''])
    def test_unknown_frame_rejected(self):self.assert_bad_frames([{}])
    def test_missing_usage_rejected(self):self.assert_bad_frames([b'{}'])
    def test_missing_payload_rejected(self):self.assert_bad_frames([UsageFrame(0,0)])
    def test_after_final_usage_rejected(self):self.assert_bad_frames([b'{}',UsageFrame(0,0),b'x'])
    def test_excess_frame_count_rejected(self):self.assert_bad_frames([b'x']*257)
    def test_over_cap_output_rejected(self):self.assert_bad_frames([b'{}',UsageFrame(10,6)])
    def test_invalid_input_usage_rejected(self):self.assert_bad_frames([b'{}',UsageFrame(True,0)])

    def test_exact_byte_and_frame_caps_are_inclusive(self):
        # Independent valid exact-byte request, then exact frame count.
        async def exact(request):
            yield b'x'*MAX_BYTES
            yield UsageFrame(0,0)
        adapter=stream_adapter('fixture',exact)
        request=AdapterRequest(b'[]','0'*64,'offline/test',1000,5,MAX_BYTES)
        self.assertEqual(len(adapter.send(request).payload),MAX_BYTES)
        async def frames(request):
            for _ in range(255):yield b'x'
            yield UsageFrame(0,0)
        self.assertEqual(len(stream_adapter('fixture',frames).send(request).payload),255)

    def test_bad_config_and_request_denied(self):
        for revision,factory in ((None,lambda _:None),('',lambda _:None),('x',None)):
            with self.assertRaises(AdvisoryError):stream_adapter(revision,factory)
        adapter=stream_adapter('fixture',lambda _:None)
        with self.assertRaises(AdvisoryError):adapter.send({})
        request=AdapterRequest(b'[]','0'*64,'offline/test',0,5,MAX_BYTES)
        with self.assertRaises(AdvisoryError):adapter.send(request)

    def test_existing_loop_rejected_without_creating_unawaited_coroutine(self):
        request=AdapterRequest(b'[]','0'*64,'offline/test',1000,5,MAX_BYTES)
        async def existing():
            with self.assertRaises(AdvisoryError):stream_adapter('fixture',lambda _:None).send(request)
        asyncio.run(existing())
