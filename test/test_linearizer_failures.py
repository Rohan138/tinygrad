# ruff: noqa: E501
import unittest, random
import numpy as np
from tinygrad.codegen.linearizer import Linearizer
from tinygrad.features.search import Opt, OptOps
from tinygrad import Device, dtypes, Tensor
from tinygrad.helpers import OSX, CI
from test.external.fuzz_linearizer import run_linearizer, get_fuzz_rawbufs, get_fuzz_rawbuf_like

# stuff needed to unpack a kernel
from tinygrad.ops import LazyOp, BinaryOps, UnaryOps, ReduceOps, BufferOps, MemBuffer, ConstBuffer, get_lazyop_info
from tinygrad.shape.shapetracker import ShapeTracker
from tinygrad.shape.view import View
inf, nan = float('inf'), float('nan')

def helper_test_lin(lin: Linearizer, opts, failed_platforms):
  rawbufs = get_fuzz_rawbufs(lin)
  var_vals = {v: random.randint(v.min, v.max) for v in lin.ast.vars()}

  assert run_linearizer(lin, rawbufs, var_vals) == "PASS" or Device.DEFAULT in failed_platforms, "Failed running non-optimized ast"
  ground_truth = np.frombuffer(rawbufs[0].as_buffer(), rawbufs[0].dtype.np)

  for opt in opts:
    try:
      lin.apply_opt(opt)
    except AssertionError:
      # it's considered fixed if we invalidated the opts
      assert Device.DEFAULT not in failed_platforms

  rawbufs[0] = get_fuzz_rawbuf_like(rawbufs[0], zero=True)
  linearizer_passed = (run_linearizer(lin, rawbufs, var_vals) == "PASS")
  output_passed = np.allclose(ground_truth, np.frombuffer(rawbufs[0].as_buffer(), rawbufs[0].dtype.np), rtol=1e-2, atol=1e-2)
  if Device.DEFAULT not in failed_platforms:
    assert linearizer_passed and output_passed
  else:
    assert not linearizer_passed or not output_passed

def helper_add_store(op):
  info = get_lazyop_info(op)
  return LazyOp(BufferOps.STORE, (op, ), MemBuffer(0, info.dtype, ShapeTracker.from_shape(info.shape)))

@unittest.skipIf(CI and Device.DEFAULT=="CUDA", "failed on CUDA CI")
class TestLinearizerFailures(unittest.TestCase):
  def setUp(self):
    random.seed(42)
    np.random.seed(42)
    Tensor.manual_seed(42)

  def test_failure_1(self):
    ast = LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(32, 16, 16), strides=(16, 1, 0), offset=0, mask=None, contiguous=False),)))),), arg=(32, 16, 1)), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=2, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(32, 16, 1), strides=(0, 1, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(32, 16, 1), strides=(16, 1, 0), offset=0, mask=None, contiguous=True),))))), arg=None)
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), [], failed_platforms=[])

  def test_failure_2(self):
    ast = LazyOp(op=ReduceOps.MAX, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(32, 2, 111, 27), strides=(6160, 3080, 28, 1), offset=0, mask=((0, 32), (0, 2), (0, 110), (0, 27)), contiguous=False), View(shape=(32, 2, 37, 9, 2, 2), strides=(5994, 2997, 81, 3, 27, 1), offset=0, mask=None, contiguous=False))))),), arg=(32, 2, 37, 9, 1, 1))
    opts = [Opt(op=OptOps.LOCAL, axis=0, amt=32)]
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), opts, failed_platforms=["CPU", "TORCH"])

  @unittest.skipIf(CI and Device.DEFAULT=="METAL", "behaves differently on METAL CI")
  def test_failure_3(self):
    ast = LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(32, 8, 16, 16), strides=(2048, 256, 16, 1), offset=0, mask=None, contiguous=True),)))),), arg=(32, 8, 16, 1))
    opts = [Opt(op=OptOps.GROUP, axis=0, amt=4), Opt(op=OptOps.UPCAST, axis=0, amt=4), Opt(op=OptOps.UPCAST, axis=0, amt=2), Opt(op=OptOps.UNROLL, axis=1, amt=0), Opt(op=OptOps.UPCAST, axis=0, amt=4), Opt(op=OptOps.LOCAL, axis=0, amt=2), Opt(op=OptOps.LOCAL, axis=0, amt=2), Opt(op=OptOps.UPCAST, axis=1, amt=0), Opt(op=OptOps.LOCAL, axis=0, amt=32)]
    # METAL: AssertionError: Error Domain=AGXMetalG13X Code=3 "Threadgroup memory size (65536) exceeds the maximum threadgroup memory allowed (32768)" UserInfo={NSLocalizedDescription=Threadgroup memory size (65536) exceeds the maximum threadgroup memory allowed (32768)}
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), opts, failed_platforms=["METAL", "GPU", "CUDA"])

  def test_failure_4(self):
    ast = LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 1, 1, 4, 1, 12, 2, 29), strides=(0, 0, 0, 2, 0, 216, 1, 8), offset=0, mask=((0, 1), (0, 1), (0, 1), (0, 4), (0, 1), (0, 11), (0, 2), (0, 27)), contiguous=False), View(shape=(1, 1, 1, 4, 22, 84), strides=(0, 0, 0, 696, 58, 1), offset=0, mask=((0, 1), (0, 1), (0, 1), (0, 4), (0, 12), (0, 58)), contiguous=False), View(shape=(1, 1, 1, 4, 2, 11, 3, 28), strides=(0, 0, 0, 1848, 924, 84, 28, 1), offset=0, mask=None, contiguous=True))))),), arg=(1, 1, 1, 4, 1, 11, 1, 28))
    opts = [Opt(op=OptOps.LOCAL, axis=2, amt=4), Opt(op=OptOps.UPCAST, axis=0, amt=2), Opt(op=OptOps.UPCAST, axis=0, amt=0), Opt(op=OptOps.LOCAL, axis=2, amt=2), Opt(op=OptOps.UPCAST, axis=3, amt=0), Opt(op=OptOps.UPCAST, axis=2, amt=0), Opt(op=OptOps.UNROLL, axis=0, amt=0), Opt(op=OptOps.UPCAST, axis=1, amt=0), Opt(op=OptOps.NOLOCALS, axis=None, amt=None)]
    # related to OptOps.NOLOCALS
    # IndexError: list index out of range
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), opts, failed_platforms=["METAL", "WEBGPU"])

  def test_failure_5(self):
    ast = LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=0.1464405059814453, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(2, 1, 4, 1, 3, 1, 4, 1), strides=(0, 0, 0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False),)))), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(2, 1, 4, 1, 3, 1, 4, 1), strides=(0, 0, 0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(2, 1, 4, 1, 3, 1, 4, 1), strides=(0, 0, 0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=0.1464405059814453, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(2, 1, 4, 1, 3, 1, 4, 1), strides=(0, 0, 0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False),)))), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(2, 1, 4, 1, 3, 1, 4, 1), strides=(0, 0, 0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(2, 1, 4, 1, 3, 1, 4, 1), strides=(0, 0, 0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None)), arg=None),), arg=(1, 1, 1, 1, 1, 1, 1, 1))
    opts = [Opt(op=OptOps.UNROLL, axis=0, amt=4), Opt(op=OptOps.UNROLL, axis=0, amt=0)]
    # EXEC_ERROR, it has no global_size
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), opts, failed_platforms=[])

  def test_failure_6(self):
    ast = LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=-1.0, dtype=dtypes.int32, st=ShapeTracker(views=(View(shape=(11, 19), strides=(0, 0), offset=0, mask=((0, 11), (9, 19)), contiguous=False), View(shape=(10, 10), strides=(1, 20), offset=0, mask=None, contiguous=False))))),), arg=(10, 1)), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=10.0, dtype=dtypes.int32, st=ShapeTracker(views=(View(shape=(10, 1), strides=(0, 0), offset=0, mask=None, contiguous=False),))))), arg=None)
    opts = [Opt(op=OptOps.UPCAST, axis=0, amt=2), Opt(op=OptOps.UPCAST, axis=0, amt=0)]
    # COMPILE FAILED, KeyError: UOps.CONST
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), opts, failed_platforms=[])

  @unittest.skipIf(Device.DEFAULT=="LLVM", "Segmentation fault")
  def test_failure_7(self):
    ast = LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 32, 6, 8, 4, 6, 8, 4), strides=(2048, 64, 6291456, 8, 0, 1048576, 1, 0), offset=0, mask=((0, 512), (0, 32), (0, 6), (0, 8), (0, 1), (0, 6), (0, 8), (0, 1)), contiguous=False), View(shape=(512, 32, 6, 35, 6, 35), strides=(1179648, 36864, 6144, 192, 32, 1), offset=0, mask=((0, 512), (0, 32), (0, 6), (0, 32), (0, 6), (0, 32)), contiguous=False), View(shape=(512, 32, 238, 238), strides=(1411200, 44100, 210, 1), offset=0, mask=((0, 512), (0, 32), (0, 210), (0, 210)), contiguous=False), View(shape=(512, 32, 7, 34, 7, 34), strides=(1812608, 56644, 8092, 238, 34, 1), offset=0, mask=None, contiguous=True))))),), arg=(512, 32, 1, 34, 1, 34))
    opts = [Opt(op=OptOps.UPCAST, axis=0, amt=4)]
    # test/test_linearizer_failures.py Fatal Python error: Segmentation fault
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), opts, failed_platforms=["LLVM"])

  @unittest.skipIf((Device.DEFAULT=="LLVM" and not OSX) or (Device.DEFAULT == "GPU" and CI), "Segmentation fault on ubuntu, GPU requires cl_khr_fp16")
  def test_failure_8(self):
    ast = LazyOp(op=UnaryOps.SQRT, src=(LazyOp(op=BinaryOps.DIV, src=(LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 1, 1), strides=(0, 0, 0), offset=0, mask=None, contiguous=True),)))), LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.half, st=ShapeTracker(views=(View(shape=(1, 1, 4096), strides=(0, 0, 1), offset=0, mask=None, contiguous=True),)))), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=2, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 1, 4096), strides=(0, 0, 1), offset=0, mask=None, contiguous=True),))))), arg=None), LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.half, st=ShapeTracker(views=(View(shape=(1, 1, 4096), strides=(0, 0, 1), offset=0, mask=None, contiguous=True),)))), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=2, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 1, 4096), strides=(0, 0, 1), offset=0, mask=None, contiguous=True),))))), arg=None)), arg=None),), arg=(1, 1, 1)), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=0.000244140625, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 1, 1), strides=(0, 0, 0), offset=0, mask=None, contiguous=True),))))), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1e-06, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 1, 1), strides=(0, 0, 0), offset=0, mask=None, contiguous=True),))))), arg=None)), arg=None),), arg=None)
    opts = [Opt(op=OptOps.UNROLL, axis=0, amt=4), Opt(op=OptOps.UNROLL, axis=0, amt=4), Opt(op=OptOps.UNROLL, axis=0, amt=4), Opt(op=OptOps.UNROLL, axis=0, amt=4)]
    # fatal error: bracket nesting level exceeded maximum of 256
    # note: use -fbracket-depth=N to increase maximum nesting level
    ast = helper_add_store(ast)
    helper_test_lin(Linearizer(ast), opts, failed_platforms=["CLANG", "METAL", "WEBGPU"])

  def test_failure_9(self):
    ast = LazyOp(op=BufferOps.STORE, src=(LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 2, 1, 3, 1, 1, 1, 1, 5, 15, 5, 3, 4), strides=(0, 3, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False),)))), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=2, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 2, 1, 3, 1, 1, 1, 1, 5, 15, 5, 3, 4), strides=(0, 4500, 0, 0, 0, 0, 0, 0, 900, 60, 12, 4, 1), offset=0, mask=None, contiguous=False),))))), arg=None),), arg=(1, 1, 1, 3, 1, 1, 1, 1, 5, 15, 5, 3, 4)),), arg=MemBuffer(idx=0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 1, 1, 3, 1, 1, 1, 1, 5, 15, 5, 3, 4), strides=(0, 0, 0, 4500, 0, 0, 0, 0, 900, 60, 12, 4, 1), offset=0, mask=None, contiguous=True),))))
    opts = [Opt(op=OptOps.UPCAST, axis=1, amt=2), Opt(op=OptOps.UPCAST, axis=0, amt=0), Opt(op=OptOps.PADTO, axis=0, amt=32)]
    helper_test_lin(Linearizer(ast), opts, failed_platforms=[])

  @unittest.skipIf((Device.DEFAULT=="LLVM" and not OSX) or (Device.DEFAULT == "GPU" and CI), "Segmentation fault on ubuntu, GPU requires cl_khr_fp16")
  def test_failure_10(self):
    ast = LazyOp(op=BufferOps.STORE, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.half, st=ShapeTracker(views=(View(shape=(1, 1, 1024, 50257), strides=(0, 0, 0, 1), offset=0, mask=None, contiguous=False),)))), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=2, dtype=dtypes.half, st=ShapeTracker(views=(View(shape=(1, 1, 1024, 50257), strides=(0, 0, 1, 1024), offset=0, mask=None, contiguous=False),))))), arg=None),), arg=(1, 1, 1024, 1)), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=3, dtype=dtypes.half, st=ShapeTracker(views=(View(shape=(1, 1, 1024, 1), strides=(0, 0, 1, 0), offset=0, mask=None, contiguous=True),))))), arg=None),), arg=MemBuffer(idx=0, dtype=dtypes.half, st=ShapeTracker(views=(View(shape=(1, 1, 1024, 1), strides=(0, 0, 1, 0), offset=0, mask=None, contiguous=True),))))
    opts = []
    # Shader '' parsing error: unknown type: 'f16'
    helper_test_lin(Linearizer(ast), opts, failed_platforms=["WEBGPU"])

  def test_failure_11(self):
    src = LazyOp(op=BinaryOps.DIV, src=(LazyOp(op=ReduceOps.SUM, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.SUB, src=(LazyOp(op=BinaryOps.MAX, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True),)))), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=2, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=0.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=3, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.DIV, src=(LazyOp(op=BinaryOps.SUB, src=(LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 3, 3, 2, 2), strides=(0, 0, 0, 0, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True))))), LazyOp(op=UnaryOps.CAST, src=(LazyOp(op=BinaryOps.CMPLT, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BinaryOps.SUB, src=(LazyOp(op=BinaryOps.MAX, src=(LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=1, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True))))), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=2, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=0.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=3, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None), LazyOp(op=UnaryOps.SQRT, src=(LazyOp(op=UnaryOps.CAST, src=(LazyOp(op=BinaryOps.DIV, src=(LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(64,), strides=(0,), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True))))), LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=4, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(64,), strides=(1,), offset=0, mask=None, contiguous=True), View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True))))), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=5.425347222222222e-05, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(64,), strides=(0,), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1e-05, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(64,), strides=(0,), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None)), arg=None),), arg=(dtypes.float, False)),), arg=None)), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=0.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 6, 6), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 3, 2, 2), strides=(2304, 36, 12, 2, 6, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=5, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 3, 3, 2, 2), strides=(576, 9, 3, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None),), arg=(dtypes.float,False))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=6, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 3, 3, 2, 2), strides=(576, 9, 3, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None), LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=7, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(512, 64, 3, 3, 2, 2), strides=(576, 9, 3, 1, 0, 0), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 3, 2, 3, 2), strides=(2304, 36, 12, 2, 4, 1), offset=0, mask=None, contiguous=False), View(shape=(512, 64, 6, 6), strides=(2304, 36, 6, 1), offset=0, mask=None, contiguous=True)))))), arg=None)), arg=None),), arg=(1, 64, 1, 1)), LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=UnaryOps.SQRT, src=(LazyOp(op=UnaryOps.CAST, src=(LazyOp(op=BinaryOps.DIV, src=(LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 64, 1, 1), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False),)))), LazyOp(op=BinaryOps.ADD, src=(LazyOp(op=BinaryOps.MUL, src=(LazyOp(op=BufferOps.LOAD, src=(), arg=MemBuffer(idx=4, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 64, 1, 1), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=True),)))), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=5.425347222222222e-05, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 64, 1, 1), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=1e-05, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 64, 1, 1), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None)), arg=None),), arg=(dtypes.float, False)),), arg=None), LazyOp(op=BufferOps.CONST, src=(), arg=ConstBuffer(val=2.0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 64, 1, 1), strides=(0, 0, 0, 0), offset=0, mask=None, contiguous=False),))))), arg=None)), arg=None)
    ast = LazyOp(op=BufferOps.STORE, src=(src,), arg=MemBuffer(idx=0, dtype=dtypes.float, st=ShapeTracker(views=(View(shape=(1, 64, 1, 1), strides=(0, 1, 0, 0), offset=0, mask=None, contiguous=True),))))
    helper_test_lin(Linearizer(ast), [], failed_platforms=[])

if __name__ == '__main__':
  unittest.main()
