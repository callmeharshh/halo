// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @title GuardVault
/// @notice On-chain guardrails for AI agents that move money on behalf of people who cannot use a
///         keyboard or mouse (voice / eye-gaze controlled). The vault OWNER (e.g. a family member) funds the
///         vault and sets the spending policy, the trusted contact book and which AGENT key (the elderly or
///         disabled user's device) may spend. The agent can spend only inside that policy and cannot change it,
///         so even a hijacked, hallucinating or scammed AI agent cannot exceed what the owner allowed.
///         The owner can pause or revoke the agent at any time.
///         Every transfer records HOW it was approved (voice, double-blink, button, ...).
contract GuardVault {
    struct Policy {
        bool configured;
        bool trustedOnly;   // only pay addresses saved in the owner's contact book
        bool paused;        // owner's emergency stop: no agent spending while true
        uint128 maxPerTx;   // wei; 0 = nothing may be sent
        uint128 dailyLimit; // wei per UTC day
        address agent;      // hot key (the voice agent) allowed to call guardedSend for the owner
    }

    uint256 public constant MAX_CONTACTS = 50;

    mapping(address => uint256) public balanceOf;
    mapping(address => Policy) public policyOf;
    mapping(address => mapping(bytes32 => address)) private _contacts;
    mapping(address => string[]) private _contactNames;                  // enumerable so devices can list them
    mapping(address => mapping(bytes32 => uint256)) private _contactIdx; // index + 1 (0 = absent)
    mapping(address => uint256) public spentInDay;
    mapping(address => uint256) public currentDay;

    uint256 public totalTransfers;
    uint256 public totalVolume;

    event Deposited(address indexed owner, uint256 amount);
    event Withdrawn(address indexed owner, uint256 amount);
    event PolicySet(address indexed owner, uint128 maxPerTx, uint128 dailyLimit, bool trustedOnly);
    event AgentSet(address indexed owner, address indexed agent);
    event PausedSet(address indexed owner, bool paused);
    event ContactSet(address indexed owner, string name, address indexed who);
    event ContactRemoved(address indexed owner, string name);
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

    function setPaused(bool paused) external {
        policyOf[msg.sender].paused = paused;
        emit PausedSet(msg.sender, paused);
    }

    /// @param name lowercase contact name, e.g. "alice" (clients normalise before calling)
    function setContact(string calldata name, address who) external {
        require(who != address(0), "zero address");
        require(bytes(name).length > 0 && bytes(name).length <= 32, "bad name");
        bytes32 key = keccak256(bytes(name));
        if (_contactIdx[msg.sender][key] == 0) {
            require(_contactNames[msg.sender].length < MAX_CONTACTS, "too many contacts");
            _contactNames[msg.sender].push(name);
            _contactIdx[msg.sender][key] = _contactNames[msg.sender].length;
        }
        _contacts[msg.sender][key] = who;
        emit ContactSet(msg.sender, name, who);
    }

    function removeContact(string calldata name) external {
        bytes32 key = keccak256(bytes(name));
        uint256 idx = _contactIdx[msg.sender][key];
        require(idx != 0, "unknown contact");
        string[] storage names = _contactNames[msg.sender];
        uint256 last = names.length;
        if (idx != last) {  // move the last name into the freed slot
            string memory moved = names[last - 1];
            names[idx - 1] = moved;
            _contactIdx[msg.sender][keccak256(bytes(moved))] = idx;
        }
        names.pop();
        delete _contactIdx[msg.sender][key];
        delete _contacts[msg.sender][key];
        emit ContactRemoved(msg.sender, name);
    }

    function contactOf(address owner, string calldata name) external view returns (address) {
        return _contacts[owner][keccak256(bytes(name))];
    }

    /// @notice All saved contacts of an owner (names and addresses, same order).
    function contactsOf(address owner) external view returns (string[] memory names, address[] memory addrs) {
        names = _contactNames[owner];
        addrs = new address[](names.length);
        for (uint256 i = 0; i < names.length; i++) {
            addrs[i] = _contacts[owner][keccak256(bytes(names[i]))];
        }
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
        require(!p.paused || msg.sender == owner, "paused by owner");

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
