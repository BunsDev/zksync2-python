import importlib.resources as pkg_resources

from eth_typing import HexStr
from web3 import Web3
from hashlib import sha256
from typing import Optional
import json
from web3.types import Nonce, TxReceipt
from eth_utils.crypto import keccak
from .. import contract_abi
from ..core.utils import pad_front_bytes, get_data, int_to_bytes

icontract_deployer_abi_cache = None


def _icontract_deployer_abi_default():
    global icontract_deployer_abi_cache

    if icontract_deployer_abi_cache is None:
        with pkg_resources.path(contract_abi, "IContractDeployer.json") as p:
            with p.open(mode='r') as json_file:
                data = json.load(json_file)
                icontract_deployer_abi_cache = data
    return icontract_deployer_abi_cache


class ContractDeployer:
    DEFAULT_SALT = b'\0' * 32
    CREATE_FUNC = "create"
    CREATE2_FUNC = "create2"
    MAX_BYTE_CODE_LENGTH = 2 ** 16
    # INFO: see implementation of: class ByteStringEncoder(BaseEncoder):
    EMPTY_BYTES = b''

    CREATE_PREFIX = keccak(text="zksyncCreate")
    CREATE2_PREFIX = keccak(text="zksyncCreate2")

    def __init__(self, web3: Web3, abi: Optional[dict] = None):
        self.web3 = web3
        if abi is None:
            abi = _icontract_deployer_abi_default()

        self.contract_deployer = self.web3.eth.contract(address=None, abi=abi)

    def _hash_byte_code(self, bytecode: bytes) -> bytes:
        bytecode_len = int(len(bytecode) / 32)
        if bytecode_len > self.MAX_BYTE_CODE_LENGTH:
            raise OverflowError("ContractDeployer._hash_byte_code, bytecode length must be less than 2^16")
        byte_code_hash = bytes.fromhex(sha256(bytecode).hexdigest())
        ret = bytecode_len.to_bytes(2, byteorder='big') + byte_code_hash[2:]
        return ret

    def encode_create2(self, bytecode: bytes,
                       call_data: Optional[bytes] = None,
                       salt: Optional[bytes] = None) -> HexStr:

        # INFO: function encoding under the Python is different from web3 java
        #       Reason: class ByteStringEncoder(BaseEncoder): for empty bytes generates 32 bytes empty value
        #       meanwhile under Web3 java it's empty array
        #       Under the Solidity engine it must be the same values

        if salt is None:
            salt = self.DEFAULT_SALT
        if call_data is None:
            call_data = self.EMPTY_BYTES

        if len(salt) != 32:
            raise OverflowError("Salt data must be 32 length")

        bytecode_hash = self._hash_byte_code(bytecode)
        args = (
            salt,
            bytecode_hash,
            0,
            call_data
        )

        encoded_function = self.contract_deployer.encodeABI(fn_name=self.CREATE2_FUNC, args=args)
        return HexStr(encoded_function)

    def encode_create(self, bytecode: bytes, call_data: Optional[bytes] = None, salt_data: Optional[bytes] = None):
        if salt_data is None:
            salt_data = self.DEFAULT_SALT
        if call_data is None:
            call_data = self.EMPTY_BYTES

        if len(salt_data) != 32:
            raise OverflowError("Salt data must be 32 length")

        bytecode_hash = self._hash_byte_code(bytecode)
        args = [
            salt_data,
            bytecode_hash,
            0,
            call_data
        ]
        encoded_function = self.contract_deployer.encodeABI(fn_name=self.CREATE_FUNC, args=args)
        return HexStr(encoded_function)

    def compute_l2_create_address(self, sender: HexStr, nonce: Nonce) -> HexStr:
        sender_bytes = get_data(sender)
        sender_bytes = pad_front_bytes(sender_bytes, 32)
        nonce = int_to_bytes(nonce)
        nonce_bytes = pad_front_bytes(nonce, 32)
        result = self.CREATE_PREFIX + sender_bytes + nonce_bytes
        sha_result = keccak(result)
        address = sha_result[12:]
        address = "0x" + address.hex()
        return HexStr(Web3.toChecksumAddress(address))

    def compute_l2_create2_address(self,
                                   sender: HexStr,
                                   bytecode: bytes,
                                   constructor: bytes,
                                   salt: bytes):
        if len(salt) != 32:
            raise OverflowError("Salt data must be 32 length")

        sender_bytes = get_data(sender)
        sender_bytes = pad_front_bytes(sender_bytes, 32)
        bytecode_hash = self._hash_byte_code(bytecode)
        # INFO: working for empty values meanwhile sha256 gives different result
        ctor_hash = keccak(constructor)
        result = self.CREATE2_PREFIX + sender_bytes + salt + bytecode_hash + ctor_hash
        sha_result = keccak(result)
        address = sha_result[12:]
        address = "0x" + address.hex()
        return HexStr(Web3.toChecksumAddress(address))

    def extract_contract_address(self, receipt: TxReceipt) -> HexStr:
        result = self.contract_deployer.events.ContractDeployed().processReceipt(receipt)
        entry = result[1]["args"]
        addr = entry["contractAddress"]
        return addr

