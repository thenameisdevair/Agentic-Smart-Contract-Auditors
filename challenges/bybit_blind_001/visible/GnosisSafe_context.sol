// SPDX-License-Identifier: LGPL-3.0-only
// Context file: key excerpts from the Safe (GnosisSafe) contracts
// relevant to a cold wallet holding significant ETH and ERC20 assets.
// This is NOT the full codebase — it is an illustrative subset for analysis.

pragma solidity >=0.7.0 <0.9.0;

// =============================================================================
// PROXY: GnosisSafeProxy
//
// The cold wallet is deployed as a proxy. The proxy delegates all calls to
// a `masterCopy` (implementation) address stored in a dedicated storage slot.
// =============================================================================

contract GnosisSafeProxy {
    // keccak256("master_copy") - 1
    // Storage slot for the masterCopy (implementation) address.
    // All calls are delegated to this address.
    address internal masterCopy;

    constructor(address _masterCopy) {
        require(_masterCopy != address(0), "Invalid master copy address provided");
        masterCopy = _masterCopy;
    }

    fallback() external payable {
        // solhint-disable-next-line no-inline-assembly
        assembly {
            let _masterCopy := and(sload(0), 0xffffffffffffffffffffffffffffffffffffffff)
            calldatacopy(0, 0, calldatasize())
            let success := delegatecall(gas(), _masterCopy, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            if eq(success, 0) { revert(0, returndatasize()) }
            return(0, returndatasize())
        }
    }
}

// =============================================================================
// IMPLEMENTATION: GnosisSafe (simplified)
//
// The implementation contract that the proxy delegates to.
// Owners manage the wallet. Transactions require a threshold of owner signatures.
// =============================================================================

contract GnosisSafe {

    // -------------------------------------------------------------------------
    // Enums / Constants
    // -------------------------------------------------------------------------

    enum Operation { Call, DelegateCall }

    address internal constant SENTINEL_OWNERS = address(0x1);
    address internal constant SENTINEL_MODULES = address(0x1);

    // -------------------------------------------------------------------------
    // Storage
    // -------------------------------------------------------------------------

    // masterCopy slot (slot 0) — set by proxy constructor, readable via proxy storage
    address internal masterCopy;

    // Module linked list: modules can execute transactions without owner sigs
    mapping(address => address) internal modules;

    // Owner linked list + threshold
    mapping(address => address) internal owners;
    uint256 internal ownerCount;
    uint256 internal threshold;

    // Nonce for replay protection
    uint256 public nonce;

    // -------------------------------------------------------------------------
    // Module management
    // -------------------------------------------------------------------------

    /// @dev Enables a new module.
    /// Only callable by the Safe itself (i.e., through a properly signed tx).
    function enableModule(address module) public authorized {
        require(module != address(0) && module != SENTINEL_MODULES, "GS101");
        require(modules[module] == address(0), "GS102");
        modules[module] = modules[SENTINEL_MODULES];
        modules[SENTINEL_MODULES] = module;
    }

    /// @dev Disables a module.
    function disableModule(address prevModule, address module) public authorized {
        require(module != address(0) && module != SENTINEL_MODULES, "GS101");
        require(modules[prevModule] == module, "GS103");
        modules[prevModule] = modules[module];
        modules[module] = address(0);
    }

    /// @dev Returns whether an address is an enabled module.
    function isModuleEnabled(address module) public view returns (bool) {
        return SENTINEL_MODULES != module && modules[module] != address(0);
    }

    // -------------------------------------------------------------------------
    // Transaction execution
    // -------------------------------------------------------------------------

    /// @dev Allows a module to execute a Safe transaction WITHOUT requiring owner signatures.
    /// @param to Destination address of module transaction.
    /// @param value Ether value of module transaction.
    /// @param data Data payload of module transaction.
    /// @param operation Operation type of module transaction: 0 = Call, 1 = DelegateCall.
    function execTransactionFromModule(
        address to,
        uint256 value,
        bytes memory data,
        Operation operation
    ) public virtual returns (bool success) {
        // Only enabled modules may call this
        require(
            msg.sender != SENTINEL_MODULES && modules[msg.sender] != address(0),
            "GS104"
        );
        if (operation == Operation.DelegateCall) {
            // solhint-disable-next-line no-inline-assembly
            assembly {
                success := delegatecall(gas(), to, add(data, 0x20), mload(data), 0, 0)
            }
        } else {
            // solhint-disable-next-line no-inline-assembly
            assembly {
                success := call(gas(), to, value, add(data, 0x20), mload(data), 0, 0)
            }
        }
    }

    /// @dev Execute a Safe transaction confirmed by the required threshold of owners.
    /// @param to Destination address.
    /// @param value Ether value.
    /// @param data Data payload.
    /// @param operation Operation type.
    /// @param safeTxGas Gas for the safe transaction.
    /// @param baseGas Gas costs for data used to trigger the safe transaction.
    /// @param gasPrice Gas price.
    /// @param gasToken Token address for gas payment, or 0 for ETH.
    /// @param refundReceiver Address of receiver of gas payment (or 0 for tx.origin).
    /// @param signatures Packed signature data ({bytes32 r}{bytes32 s}{uint8 v}).
    function execTransaction(
        address to,
        uint256 value,
        bytes calldata data,
        Operation operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address payable refundReceiver,
        bytes memory signatures
    ) public payable virtual returns (bool success) {
        bytes32 txHash;
        {
            bytes memory txHashData = encodeTransactionData(
                to, value, data, operation, safeTxGas, baseGas, gasPrice, gasToken, refundReceiver, nonce
            );
            nonce++;
            txHash = keccak256(txHashData);
            checkSignatures(txHash, txHashData, signatures);
        }
        // Execute the transaction
        success = execute(to, value, data, operation, gasleft());
    }

    /// @dev Low-level call/delegatecall dispatcher.
    function execute(
        address to,
        uint256 value,
        bytes memory data,
        Operation operation,
        uint256 txGas
    ) internal returns (bool success) {
        if (operation == Operation.DelegateCall) {
            assembly {
                success := delegatecall(txGas, to, add(data, 0x20), mload(data), 0, 0)
            }
        } else {
            assembly {
                success := call(txGas, to, value, add(data, 0x20), mload(data), 0, 0)
            }
        }
    }

    /// @dev Checks signatures of a transaction hash.
    function checkSignatures(
        bytes32 dataHash,
        bytes memory data,
        bytes memory signatures
    ) public view {
        uint256 _threshold = threshold;
        require(_threshold > 0, "GS001");
        checkNSignatures(dataHash, data, signatures, _threshold);
    }

    function checkNSignatures(
        bytes32 dataHash,
        bytes memory data,
        bytes memory signatures,
        uint256 requiredSignatures
    ) public view {
        require(signatures.length >= requiredSignatures * 65, "GS020");
        // ... signature validation loop (each signer must be an owner) ...
    }

    // -------------------------------------------------------------------------
    // Encoding helpers
    // -------------------------------------------------------------------------

    function encodeTransactionData(
        address to,
        uint256 value,
        bytes calldata data,
        Operation operation,
        uint256 safeTxGas,
        uint256 baseGas,
        uint256 gasPrice,
        address gasToken,
        address payable refundReceiver,
        uint256 _nonce
    ) public view returns (bytes memory) {
        // Returns EIP-712 encoded transaction data for signing
        // ...
    }

    // -------------------------------------------------------------------------
    // Access modifier
    // -------------------------------------------------------------------------

    /// @dev Modifier to only allow calls from the Safe itself (i.e., via execTransaction).
    modifier authorized() {
        require(msg.sender == address(this), "GS031");
        _;
    }
}

// =============================================================================
// ADDITIONAL CONTEXT
//
// Deployment:
//   - The cold wallet proxy is deployed at a known address on Ethereum mainnet.
//   - The proxy's masterCopy slot currently points to a legitimate GnosisSafe implementation.
//   - The wallet holds: ~401,346 ETH, 8,000 mETH, 15,000 cmETH, 90,375 stETH.
//   - The wallet has 3 owners. Threshold is 2-of-3.
//
// Module system:
//   - Modules are contracts that have been authorized by the Safe via execTransaction.
//   - An enabled module can call execTransactionFromModule() at any time without owner sigs.
//   - execTransactionFromModule supports both Call and DelegateCall operations.
//
// Questions to consider:
//   - What can an attacker do if they control an enabled module?
//   - What happens to the proxy's storage when a DelegateCall is made from within the proxy context?
//   - Is the masterCopy address immutable once the proxy is deployed?
//   - How does execTransactionFromModule interact with the proxy's storage layout?
// =============================================================================
