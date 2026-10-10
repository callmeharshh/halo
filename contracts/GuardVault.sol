// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @title GuardVault
/// @notice On-chain guardrails for AI agents that move money on behalf of people who cannot use a
///         keyboard or mouse (voice / eye-gaze controlled). Every user has their own vault, spending
///         policy, trusted contact book and approved agent key. The policy is enforced by the contract,
///         so even a hijacked or hallucinating AI agent cannot exceed what the user allowed.
///         Every transfer records HOW it was approved (voice, double-blink, button, ...).
contract GuardVault {
    struct Policy {
        bool configured;
        bool trustedOnly;   // only pay addresses saved in the user's contact book
        uint128 maxPerTx;   // wei; 0 = nothing may be sent
        uint128 dailyLimit; // wei per UTC day
        address agent;      // hot key (the voice agent) allowed to call guardedSend for the user
    }

    mapping(address => uint256) public balanceOf;
    mapping(address => Policy) public policyOf;
    mapping(address => mapping(bytes32 => address)) private _contacts;
    mapping(address => uint256) public spentInDay;
    mapping(address => uint256) public currentDay;

    uint256 public totalTransfers;
    uint256 public totalVolume;

    event Deposited(address indexed owner, uint256 amount);
    event Withdrawn(address indexed owner, uint256 amount);
    event PolicySet(address indexed owner, uint128 maxPerTx, uint128 dailyLimit, bool trustedOnly);
    event AgentSet(address indexed owner, address indexed agent);
    event ContactSet(address indexed owner, string name, address indexed who);
    event GuardedTransfer(
        address indexed owner,
        address indexed to,
        string contactName,
        uint256 amount,
        string approvedBy,
        uint256 timestamp
    );

    uint256 private _lock = 1;

    modifier nonReentrant() {
        require(_lock == 1, "reentrancy");
        _lock = 2;
        _;
        _lock = 1;
    }

    // ── funds ────────────────────────────────────────────────────────────────
    function deposit() external payable {
        require(msg.value > 0, "no value");
        balanceOf[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    receive() external payable {
        balanceOf[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    function withdraw(uint256 amount) external nonReentrant {
        require(balanceOf[msg.sender] >= amount, "insufficient balance");
        balanceOf[msg.sender] -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok, "withdraw failed");
        emit Withdrawn(msg.sender, amount);
    }

    // ── configuration (owner only) ───────────────────────────────────────────
    function setPolicy(uint128 maxPerTx, uint128 dailyLimit, bool trustedOnly) external {
        Policy storage p = policyOf[msg.sender];
        p.configured = true;
        p.maxPerTx = maxPerTx;
        p.dailyLimit = dailyLimit;
        p.trustedOnly = trustedOnly;
        emit PolicySet(msg.sender, maxPerTx, dailyLimit, trustedOnly);
    }

    function setAgent(address agent) external {
        policyOf[msg.sender].agent = agent;
        emit AgentSet(msg.sender, agent);
    }

    /// @param name lowercase contact name, e.g. "alice" (clients normalise before calling)
    function setContact(string calldata name, address who) external {
        require(who != address(0), "zero address");
        require(bytes(name).length > 0 && bytes(name).length <= 32, "bad name");
        _contacts[msg.sender][keccak256(bytes(name))] = who;
        emit ContactSet(msg.sender, name, who);
    }

    function contactOf(address owner, string calldata name) external view returns (address) {
        return _contacts[owner][keccak256(bytes(name))];
    }

    // ── the guarded transfer ─────────────────────────────────────────────────
    /// @notice Send MON from `owner`'s vault. Callable by the owner or their approved agent key.
    /// @param contactName if non-empty, the recipient is resolved from the owner's on-chain contacts
    /// @param to          raw recipient, only used when contactName is empty (and trustedOnly is off)
    /// @param approvedBy  how the human approved it: "voice", "double-blink", "button", ...
    function guardedSend(
        address owner,
        string calldata contactName,
        address to,
        uint256 amount,
        string calldata approvedBy
    ) external nonReentrant {
        Policy memory p = policyOf[owner];
        require(p.configured, "policy not set");
        require(msg.sender == owner || msg.sender == p.agent, "not owner or agent");

        address dest = to;
        if (bytes(contactName).length > 0) {
            dest = _contacts[owner][keccak256(bytes(contactName))];
            require(dest != address(0), "unknown contact");
        } else {
            require(!p.trustedOnly, "recipient not a saved contact");
        }
        require(dest != address(0), "zero recipient");
        require(amount > 0, "zero amount");
        require(amount <= p.maxPerTx, "exceeds per-transaction limit");

        uint256 today = block.timestamp / 1 days;
        if (currentDay[owner] != today) {
            currentDay[owner] = today;
            spentInDay[owner] = 0;
        }
        require(spentInDay[owner] + amount <= p.dailyLimit, "exceeds daily limit");
        require(balanceOf[owner] >= amount, "insufficient vault balance");

        spentInDay[owner] += amount;
        balanceOf[owner] -= amount;
        totalTransfers += 1;
        totalVolume += amount;

        (bool ok,) = dest.call{value: amount}("");
        require(ok, "transfer failed");
        emit GuardedTransfer(owner, dest, contactName, amount, approvedBy, block.timestamp);
    }
}
