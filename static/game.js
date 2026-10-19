/**
 * WolfCha 狼人杀游戏前端逻辑 - 多人房间版
 */

class WolfChaGame {
    constructor() {
        this.ws = null;
        this.roomId = null;
        this.uid = null;
        this.isOwner = false;
        this.mySeat = null;
        this.myName = '';
        this.players = [];
        this.myRole = null;
        this.currentPhase = null;
        this.isNight = false;
        this.pendingAction = null;
        this.gameStarted = false;
        this.seats = [];
        this.playerCount = 10;
        this.isSpectator = false;
        this.currentUser = null;

        this.init();
    }

    init() {
        // 登录页
        document.getElementById('login-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.doLogin();
        });
        document.getElementById('logout-btn').addEventListener('click', () => this.doLogout());
        // 欢迎页
        document.getElementById('create-room-btn').addEventListener('click', () => this.createRoom());
        // 大厅
        document.getElementById('copy-link-btn').addEventListener('click', () => this.copyRoomLink());
        document.getElementById('start-game-btn').addEventListener('click', () => this.startGame());
        // 角色揭示
        document.getElementById('continue-btn').addEventListener('click', () => this.continueAfterRoleReveal());
        // 游戏结束
        document.getElementById('restart-btn').addEventListener('click', () => this.restartGame());
        // 发言
        document.getElementById('submit-speech-btn').addEventListener('click', () => this.submitSpeech());
        document.getElementById('speech-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.submitSpeech();
            }
        });

        // 先校验会话，再决定是否进入主界面
        this.bootstrap();
    }

    async bootstrap() {
        const authed = await this.checkAuth();
        if (authed) {
            this.enterApp();
        } else {
            this.showScreen('login-screen');
        }
    }

    async checkAuth() {
        try {
            const resp = await fetch('/api/check_auth', { credentials: 'same-origin' });
            if (!resp.ok) return false;
            const data = await resp.json();
            this.currentUser = data.username;
            return true;
        } catch (e) {
            console.error('Check auth error:', e);
            return false;
        }
    }

    enterApp() {
        document.getElementById('welcome-user').textContent = this.currentUser ? `已登录: ${this.currentUser}` : '';
        this.showScreen('welcome-screen');
        // 检查 URL 是否是房间链接
        this.checkUrlForRoom();
    }

    async doLogin() {
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');
        const btn = document.getElementById('login-btn');

        if (!username || !password) {
            errorEl.textContent = '请输入账户和密码';
            errorEl.style.display = 'block';
            return;
        }

        btn.disabled = true;
        btn.textContent = '登录中...';
        try {
            const resp = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ username, password })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                errorEl.textContent = data.detail || '登录失败';
                errorEl.style.display = 'block';
                return;
            }
            errorEl.style.display = 'none';
            document.getElementById('login-password').value = '';
            this.currentUser = data.username;
            this.enterApp();
        } catch (e) {
            console.error('Login error:', e);
            errorEl.textContent = '登录失败，请检查网络';
            errorEl.style.display = 'block';
        } finally {
            btn.disabled = false;
            btn.textContent = '登录';
        }
    }

    async doLogout() {
        try {
            await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' });
        } catch (e) {
            console.error('Logout error:', e);
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.currentUser = null;
        this.roomId = null;
        this.uid = null;
        this.isOwner = false;
        this.mySeat = null;
        this.gameStarted = false;
        history.pushState(null, '', '/');
        this.showScreen('login-screen');
    }

    checkUrlForRoom() {
        const match = window.location.pathname.match(/^\/room\/([a-zA-Z0-9-]+)/);
        if (match) {
            this.roomId = match[1];
            this.myName = localStorage.getItem('wolfcha_name') || '';
            // 直接进入大厅（需要先连 WS）
            this.joinExistingRoom();
        }
    }

    async createRoom() {
        const playerCount = parseInt(document.getElementById('player-count').value);
        const difficulty = document.getElementById('difficulty').value;
        this.myName = document.getElementById('human-name').value || '玩家';
        localStorage.setItem('wolfcha_name', this.myName);

        try {
            const resp = await fetch('/api/create_room', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ player_count: playerCount, difficulty })
            });
            if (resp.status === 401) {
                this.handleUnauthorized();
                return;
            }
            const data = await resp.json();
            this.roomId = data.room_id;
            this.uid = data.owner_id;
            this.isOwner = true;
            this.playerCount = playerCount;

            // 更新 URL
            history.pushState(null, '', `/room/${this.roomId}`);

            // 连接 WebSocket
            await this.connectWebSocket();
        } catch (e) {
            console.error('Create room error:', e);
            alert('创建房间失败');
        }
    }

    async joinExistingRoom() {
        // 生成一个访客 uid
        this.uid = localStorage.getItem('wolfcha_uid_' + this.roomId);
        if (!this.uid) {
            this.uid = crypto.randomUUID ? crypto.randomUUID() : ('' + Math.random()).slice(2);
            localStorage.setItem('wolfcha_uid_' + this.roomId, this.uid);
        }
        this.isOwner = false;

        try {
            await this.connectWebSocket();
        } catch (e) {
            console.error('Join room error:', e);
            alert('加入房间失败，房间可能不存在');
            this.showScreen('welcome-screen');
        }
    }

    connectWebSocket() {
        return new Promise((resolve, reject) => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/${this.roomId}/${this.uid}`);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                resolve();
            };

            this.ws.onmessage = (event) => {
                const message = JSON.parse(event.data);
                this.handleMessage(message);
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                reject(error);
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket closed', event.code);
                if (event.code === 4401) {
                    this.handleUnauthorized('登录状态已失效，请重新登录');
                }
            };
        });
    }

    handleMessage(message) {
        console.log('Received:', message);

        switch (message.type) {
            case 'connected':
                this.handleConnected(message.data);
                break;
            case 'room_update':
                this.handleRoomUpdate(message.data);
                break;
            case 'join_result':
                this.handleJoinResult(message.data);
                break;
            case 'game_start':
                this.handleGameStart(message.data);
                break;
            case 'role_reveal':
                this.handleRoleReveal(message.data);
                break;
            case 'phase_change':
                this.handlePhaseChange(message.data);
                break;
            case 'system':
                if (this.shouldShowMessage(message.data)) {
                    this.addSystemMessage(message.data.message);
                }
                break;
            case 'speech':
                this.handleSpeech(message.data);
                break;
            case 'speaker_change':
                this.handleSpeakerChange(message.data);
                break;
            case 'action':
                this.handleAction(message.data);
                break;
            case 'vote':
                this.handleVote(message.data);
                break;
            case 'vote_result':
                this.handleVoteResult(message.data);
                break;
            case 'death':
                this.handleDeath(message.data);
                break;
            case 'wait_human':
                this.handleWaitHuman(message.data);
                break;
            case 'game_end':
                this.handleGameEnd(message.data);
                break;
            case 'back_to_room':
                this.handleBackToRoom(message.data);
                break;
            case 'ping':
                break;
            case 'error':
                alert(message.data.message);
                break;
            case 'auth_error':
                this.handleUnauthorized(message.data.message);
                break;
        }
    }

    handleUnauthorized(msg) {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.currentUser = null;
        this.roomId = null;
        this.uid = null;
        this.isOwner = false;
        this.mySeat = null;
        this.gameStarted = false;
        history.pushState(null, '', '/');
        this.showScreen('login-screen');
        alert(msg || '登录状态已失效，请重新登录');
    }

    handleConnected(data) {
        this.isOwner = data.is_owner;
        this.seats = data.seats;
        this.playerCount = data.player_count;
        this.gameStarted = data.game_started;

        if (this.gameStarted) {
            const mySeatInfo = this.seats.find(s => s.occupied && s.name);
            // 检查自己是否在座位上
            const seated = this.seats.find(s => {
                // 无法直接判断 uid，通过 get_state 获取
                return false;
            });
            // 观战者或已入座玩家都请求状态
            this.ws.send(JSON.stringify({ type: 'get_state' }));
        } else {
            this.showLobby();
        }
    }

    handleRoomUpdate(data) {
        this.seats = data.seats;
        this.playerCount = data.player_count;
        this.gameStarted = data.game_started;

        if (this.gameStarted && this.mySeat === null) {
            // 观战模式：游戏开始了但没入座
            this.isSpectator = true;
            this.showScreen('game-screen');
            document.getElementById('my-role-display').textContent = '观战中';
        }

        this.renderSeats();
        this.updateLobbyUI();
    }

    handleJoinResult(data) {
        if (data.success) {
            this.mySeat = data.seat;
        } else {
            // 换座失败，回滚：从 seats 数据找回自己的真实座位
            this.mySeat = null;
            // 尝试从 seats 里找自己（通过名字匹配不可靠，所以直接置 null 让 room_update 刷新）
            alert(data.message || '操作失败');
        }
        this.renderSeats();
        this.updateLobbyUI();
    }

    handleBackToRoom(data) {
        this.seats = data.seats;
        this.playerCount = data.player_count;
        this.gameStarted = false;
        this.mySeat = null;
        this.myRole = null;
        this.players = [];
        this.isSpectator = false;
        document.getElementById('messages').innerHTML = '';
        this.showLobby();
    }

    showLobby() {
        // 设置房间链接
        const roomUrl = `${window.location.origin}/room/${this.roomId}`;
        document.getElementById('room-link').value = roomUrl;

        // 设置名字输入框
        const nameInput = document.getElementById('lobby-name-input');
        nameInput.value = this.myName || localStorage.getItem('wolfcha_name') || '';

        this.renderSeats();
        this.updateLobbyUI();
        this.showScreen('lobby-screen');
    }

    renderSeats() {
        const grid = document.getElementById('seats-grid');
        grid.innerHTML = '';

        for (let i = 0; i < this.playerCount; i++) {
            const seatInfo = this.seats.find(s => s.seat === i) || { seat: i, occupied: false };
            const card = document.createElement('div');
            card.className = 'seat-card';

            const isMine = this.mySeat === i;
            if (seatInfo.occupied) card.classList.add('occupied');
            if (isMine) card.classList.add('mine');
            if (seatInfo.is_owner) card.classList.add('owner-seat');

            card.innerHTML = `
                <div class="seat-number">${i + 1}号位</div>
                <div class="seat-icon">${seatInfo.occupied ? '🧑' : '➕'}</div>
                ${seatInfo.occupied 
                    ? `<div class="seat-player-name">${seatInfo.name}${isMine ? ' (你)' : ''}</div>` 
                    : `<div class="seat-empty-text">${this.mySeat !== null ? '点击换座' : '点击入座'}</div>`}
                ${seatInfo.is_owner ? '<div class="seat-owner-badge">房主</div>' : ''}
            `;

            if (!seatInfo.occupied) {
                if (this.mySeat === null) {
                    card.addEventListener('click', () => this.joinSeat(i));
                } else {
                    card.addEventListener('click', () => this.switchSeat(i));
                }
            } else if (isMine) {
                card.addEventListener('click', () => {
                    if (confirm('确定要离开座位吗？')) this.leaveSeat();
                });
            }

            grid.appendChild(card);
        }
    }

    updateLobbyUI() {
        const seatedCount = this.seats.filter(s => s.occupied).length;
        document.getElementById('lobby-player-count').textContent = `${this.playerCount}人局`;
        document.getElementById('lobby-seated-count').textContent = `已入座: ${seatedCount}人`;

        const startBtn = document.getElementById('start-game-btn');
        const waitMsg = document.getElementById('lobby-wait-msg');
        const nameRow = document.getElementById('lobby-name-row');

        if (this.mySeat !== null) {
            nameRow.style.display = 'none';
            waitMsg.style.display = this.isOwner ? 'none' : 'block';
            waitMsg.textContent = '等待房主开始游戏...';
        } else {
            nameRow.style.display = 'flex';
            // 游戏已开始时显示观战提示
            if (this.gameStarted) {
                waitMsg.style.display = 'block';
                waitMsg.textContent = '游戏已开始，你正在观战中';
            } else {
                waitMsg.style.display = 'none';
            }
        }

        if (this.isOwner) {
            startBtn.style.display = 'block';
            startBtn.disabled = seatedCount === 0;
            waitMsg.style.display = 'none';
        } else {
            startBtn.style.display = 'none';
        }
    }

    joinSeat(seat) {
        const nameInput = document.getElementById('lobby-name-input');
        this.myName = nameInput.value.trim() || '玩家';
        localStorage.setItem('wolfcha_name', this.myName);

        this.ws.send(JSON.stringify({
            type: 'join_seat',
            seat: seat,
            name: this.myName
        }));
    }

    leaveSeat() {
        this.ws.send(JSON.stringify({ type: 'leave_seat' }));
        this.mySeat = null;
        this.renderSeats();
        this.updateLobbyUI();
    }

    switchSeat(newSeat) {
        console.log('switchSeat called, newSeat:', newSeat, 'current mySeat:', this.mySeat);
        this.ws.send(JSON.stringify({ type: 'switch_seat', seat: newSeat }));
        // 乐观更新，失败时 handleJoinResult 会 alert
        this.mySeat = newSeat;
        this.renderSeats();
        this.updateLobbyUI();
    }

    copyRoomLink() {
        const input = document.getElementById('room-link');
        input.select();
        document.execCommand('copy');
        const btn = document.getElementById('copy-link-btn');
        btn.textContent = '已复制';
        setTimeout(() => btn.textContent = '复制', 1500);
    }

    startGame() {
        this.ws.send(JSON.stringify({ type: 'start_game' }));
    }

    handleGameStart(data) {
        this.players = data.players;
        this.gameStarted = true;

        if (this.mySeat === null) {
            // 观战模式
            this.isSpectator = true;
            this.showScreen('game-screen');
            this.renderPlayers();
            document.getElementById('my-role-display').textContent = '观战中';
            this.updateAliveCount();
        } else {
            // 正常玩家，等待角色揭示
            const myPlayer = this.players.find(p => p.seat === this.mySeat);
            if (myPlayer) myPlayer.is_human = true;
        }
    }

    handleRoleReveal(data) {
        // 观战者不会收到角色揭示
        if (this.isSpectator) return;
        // 只处理自己座位的角色揭示
        if (data.seat !== this.mySeat) return;

        this.myRole = data.role;
        const roleIcons = {
            'Villager': '👤',
            'Werewolf': '🐺',
            'Seer': '👁️',
            'Witch': '🧪',
            'Hunter': '🔫',
            'Guard': '🛡️'
        };

        document.getElementById('reveal-role-icon').textContent = roleIcons[data.role] || '👤';
        document.getElementById('reveal-role-name').textContent = data.role_text;

        const roleCard = document.getElementById('role-card');
        roleCard.className = 'role-card' + (data.role === 'Werewolf' ? ' wolf' : '');

        if (data.teammates && data.teammates.length > 0) {
            const teammatesInfo = document.getElementById('teammates-info');
            const teammatesList = document.getElementById('teammates-list');
            teammatesList.innerHTML = data.teammates.map(t =>
                `<span class="teammate-badge">${t.seat + 1}号 ${t.name}</span>`
            ).join('');
            teammatesInfo.style.display = 'block';
        } else {
            document.getElementById('teammates-info').style.display = 'none';
        }

        this.showScreen('role-reveal-screen');
    }

    continueAfterRoleReveal() {
        this.showScreen('game-screen');
        this.renderPlayers();
        this.updateMyRoleDisplay();
    }

    handlePhaseChange(data) {
        this.showLoading(false);
        this.currentPhase = data.phase;
        this.isNight = data.phase.startsWith('NIGHT_');

        if (data.day) {
            document.getElementById('day-display').textContent = `第${data.day}天`;
        }

        const phaseDisplay = document.getElementById('phase-display');
        phaseDisplay.textContent = this.getPhaseDisplayText(data.phase);
        phaseDisplay.className = 'phase-badge ' + (this.isNight ? 'night' : 'day');

        if (data.phase === 'NIGHT_START' || data.phase === 'DAY_START') {
            this.showDayNightTransition(data.message || (this.isNight ? '夜幕降临' : '天亮了'));
        }
    }

    getPhaseDisplayText(phase) {
        const rolePhaseMap = {
            'NIGHT_GUARD_ACTION': 'Guard',
            'NIGHT_WOLF_ACTION': 'Werewolf',
            'NIGHT_WITCH_ACTION': 'Witch',
            'NIGHT_SEER_ACTION': 'Seer',
        };
        if (rolePhaseMap[phase]) {
            if (this.myRole === rolePhaseMap[phase]) {
                return this.getPhaseText(phase);
            }
            return '夜晚';
        }
        return this.getPhaseText(phase);
    }

    getPhaseText(phase) {
        const phaseTexts = {
            'NIGHT_START': '夜晚',
            'NIGHT_DISCUSSION': '夜晚',
            'NIGHT_GUARD_ACTION': '守卫行动',
            'NIGHT_WOLF_ACTION': '狼人行动',
            'NIGHT_WITCH_ACTION': '女巫行动',
            'NIGHT_SEER_ACTION': '预言家行动',
            'DAY_START': '天亮了',
            'DAY_SPEECH': '白天讨论',
            'DAY_VOTE': '投票阶段',
            'DAY_LAST_WORDS': '遗言阶段',
            'HUNTER_SHOOT': '猎人开枪',
            'GAME_END': '游戏结束'
        };
        return phaseTexts[phase] || phase;
    }

    showDayNightTransition(text) {
        const overlay = document.getElementById('day-night-overlay');
        document.getElementById('transition-text').textContent = text;
        overlay.style.display = 'flex';
        setTimeout(() => overlay.style.display = 'none', 2000);
    }

    handleSpeech(data) {
        this.showLoading(false);
        if (data.visibility === 'wolf_only' && this.myRole !== 'Werewolf') {
            return;
        }
        this.addSpeechMessage(data.seat, data.name, data.content, data.is_last_words);
    }

    handleSpeakerChange(data) {
        // 夜间阶段不显示发言高亮（防止泄漏角色信息）
        // 仅狼人在狼人讨论阶段可以看到队友高亮
        if (this.isNight) {
            if (this.myRole === 'Werewolf' && this.currentPhase === 'NIGHT_DISCUSSION') {
                // 狼人可以看到狼人讨论的 speaker
            } else {
                // 其他情况夜间不高亮任何人
                document.querySelectorAll('.player-card').forEach(card => {
                    card.classList.remove('speaking');
                });
                return;
            }
        }

        document.querySelectorAll('.player-card').forEach(card => {
            card.classList.remove('speaking');
        });
        const speakerCard = document.querySelector(`.player-card[data-seat="${data.seat}"]`);
        if (speakerCard) {
            speakerCard.classList.add('speaking');
        }
    }

    handleAction(data) {
        if (!this.shouldShowMessage(data)) return;
        if (data.message) {
            const isImportant = ['seer_check', 'witch_save', 'witch_poison', 'guard', 'wolf_kill'].includes(data.action);
            this.addSystemMessage(data.message, isImportant);
        }
    }

    handleVote(data) {
        this.addSystemMessage(`${data.voter_name} 投票给了 ${data.target_name}`);
    }

    handleVoteResult(data) {
        if (data.vote_detail) {
            this.addSystemMessage(`投票详情: ${data.vote_detail}`);
        }
        if (data.eliminated_seat !== null && data.eliminated_seat !== undefined) {
            this.addSystemMessage(`投票结束，${data.eliminated_seat + 1}号 ${data.eliminated_name} 被投票出局 (${data.vote_count}票)`, true);
        }
    }

    handleDeath(data) {
        data.seats.forEach(seat => {
            const player = this.players.find(p => p.seat === seat);
            if (player) player.alive = false;
        });
        this.renderPlayers();
        this.updateAliveCount();
        this.addSystemMessage(data.message, false, true);
    }

    handleWaitHuman(data) {
        // 观战者不弹操作面板
        if (this.isSpectator) return;
        if (data.player_seat !== this.mySeat) return;

        // wolf_vote 特殊处理：不覆盖当前面板，而是在消息区显示选择按钮
        if (data.action_type === 'wolf_vote') {
            this._wolfVoteAction = data;
            this._showWolfVoteInline(data);
            return;
        }

        this.pendingAction = data;
        this.showLoading(false);
        this.showActionPanel(data);
    }

    _showWolfVoteInline(data) {
        // 在消息区底部插入一个选择条
        let bar = document.getElementById('wolf-vote-bar');
        if (bar) bar.remove();

        bar = document.createElement('div');
        bar.id = 'wolf-vote-bar';
        bar.className = 'action-panel';
        bar.style.borderColor = 'var(--wolf-red)';

        const timeout = data.extra?.timeout;
        let countdownHtml = timeout ? ` <span class="countdown" id="wolf-vote-countdown">(${timeout}s)</span>` : '';

        bar.innerHTML = `<div class="action-prompt" style="color:var(--wolf-red)">选择击杀目标${countdownHtml}</div><div class="action-options" id="wolf-vote-options"></div>`;

        const container = document.querySelector('.dialog-area');
        // 插入到 action-panel 之前
        const actionPanel = document.getElementById('action-panel');
        container.insertBefore(bar, actionPanel);

        const options = document.getElementById('wolf-vote-options');
        const alivePlayers = this.players.filter(p => p.alive && p.seat !== this.mySeat);
        alivePlayers.forEach(player => {
            const btn = document.createElement('button');
            btn.className = 'action-btn danger';
            btn.textContent = `${player.seat + 1}号 ${player.name}`;
            btn.addEventListener('click', () => {
                this._submitWolfVote(player.seat);
            });
            options.appendChild(btn);
        });

        // 不袭击按钮
        const skipBtn = document.createElement('button');
        skipBtn.className = 'action-btn';
        skipBtn.textContent = '不袭击任何人';
        skipBtn.addEventListener('click', () => this._submitWolfVote(null));
        options.appendChild(skipBtn);

        // 倒计时
        if (timeout) {
            let remaining = timeout;
            this._wolfVoteTimer = setInterval(() => {
                remaining--;
                const el = document.getElementById('wolf-vote-countdown');
                if (el) el.textContent = `(${remaining}s)`;
                if (remaining <= 0) {
                    clearInterval(this._wolfVoteTimer);
                    this._wolfVoteTimer = null;
                    const b = document.getElementById('wolf-vote-bar');
                    if (b) b.remove();
                }
            }, 1000);
        }
    }

    _submitWolfVote(target) {
        if (!this._wolfVoteAction) return;
        if (this._wolfVoteTimer) {
            clearInterval(this._wolfVoteTimer);
            this._wolfVoteTimer = null;
        }
        this.ws.send(JSON.stringify({
            type: 'action',
            action_type: 'wolf_vote',
            data: target
        }));
        this._wolfVoteAction = null;
        const bar = document.getElementById('wolf-vote-bar');
        if (bar) {
            bar.innerHTML = '<div class="action-prompt" style="color:var(--accent-green)">✓ 已选择目标</div>';
            setTimeout(() => bar.remove(), 2000);
        }
    }

    showActionPanel(data) {
        const panel = document.getElementById('action-panel');
        const prompt = document.getElementById('action-prompt');
        const options = document.getElementById('action-options');
        const inputArea = document.getElementById('action-input-area');

        panel.style.display = 'block';
        options.innerHTML = '';
        inputArea.style.display = 'none';

        // 清除旧的倒计时
        if (this._countdownTimer) {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        }

        // 启动倒计时
        const timeout = data.extra?.timeout;
        if (timeout) {
            let remaining = timeout;
            const countdownEl = document.createElement('span');
            countdownEl.className = 'countdown';
            countdownEl.id = 'action-countdown';
            countdownEl.textContent = ` (${remaining}s)`;
            // 倒计时会附加到 prompt 后面

            this._countdownTimer = setInterval(() => {
                remaining--;
                const el = document.getElementById('action-countdown');
                if (el) el.textContent = ` (${remaining}s)`;
                if (remaining <= 0) {
                    clearInterval(this._countdownTimer);
                    this._countdownTimer = null;
                    panel.style.display = 'none';
                }
            }, 1000);

            // 先设置 prompt，再附加倒计时
            const setPrompt = (text) => {
                prompt.textContent = text;
                prompt.appendChild(countdownEl);
            };
            this._setPrompt = setPrompt;
        } else {
            this._setPrompt = (text) => { prompt.textContent = text; };
        }

        switch (data.action_type) {
            case 'guard':
                this._setPrompt('请选择要保护的玩家');
                this.renderPlayerOptions(options, data.extra?.last_guard_target, false, true);
                break;
            case 'wolf':
                let wolfText = '狼人请选择要击杀的玩家';
                if (data.extra?.wolf_votes) {
                    const votesInfo = Object.entries(data.extra.wolf_votes)
                        .map(([id, seat]) => `队友选择了 ${seat + 1}号`)
                        .join('，');
                    if (votesInfo) wolfText += `（${votesInfo}）`;
                }
                this._setPrompt(wolfText);
                this.renderPlayerOptions(options, null, true);
                break;
            case 'witch':
                this._setPrompt('女巫请选择行动');
                this.renderWitchOptions(options, data.extra);
                break;
            case 'seer':
                this._setPrompt('预言家请选择要查验的玩家');
                this.renderPlayerOptions(options);
                break;
            case 'wolf_chat':
                this._setPrompt('狼人讨论：请发言（超时自动结束讨论）');
                inputArea.style.display = 'block';
                document.getElementById('speech-input').value = '';
                document.getElementById('speech-input').focus();
                break;
            case 'wolf_vote':
                this._setPrompt('选择今晚击杀目标');
                this.renderPlayerOptions(options, null, false, false);
                // 加一个"不袭击"选项
                {
                    const skipBtn = document.createElement('button');
                    skipBtn.className = 'action-btn';
                    skipBtn.textContent = '不袭击任何人';
                    skipBtn.addEventListener('click', () => this.selectAction(null));
                    options.appendChild(skipBtn);
                }
                break;
            case 'speech':
            case 'last_words':
                this._setPrompt(data.action_type === 'speech' ? '请发表你的观点' : '请发表遗言');
                inputArea.style.display = 'block';
                document.getElementById('speech-input').value = '';
                document.getElementById('speech-input').focus();
                break;
            case 'vote':
                this._setPrompt('请投票选出要处决的玩家');
                this.renderPlayerOptions(options, null, false, true);
                break;
            case 'hunter':
                this._setPrompt('猎人请选择要带走的玩家');
                this.renderPlayerOptions(options);
                break;
        }
        this.scrollToBottom();
    }

    renderPlayerOptions(container, excludeSeat = null, onlyVillage = false, includeSelf = false) {
        const alivePlayers = this.players.filter(p => {
            if (!p.alive) return false;
            if (!includeSelf && p.seat === this.mySeat) return false;
            if (p.seat === excludeSeat) return false;
            if (onlyVillage && p.alignment === 'wolf') return false;
            return true;
        });

        alivePlayers.forEach(player => {
            const btn = document.createElement('button');
            btn.className = 'action-btn';
            btn.textContent = `${player.seat + 1}号 ${player.name}`;
            btn.addEventListener('click', () => this.selectAction(player.seat));
            container.appendChild(btn);
        });

        if (this.pendingAction?.action_type === 'guard') {
            const skipBtn = document.createElement('button');
            skipBtn.className = 'action-btn';
            skipBtn.textContent = '不保护任何人';
            skipBtn.addEventListener('click', () => this.selectAction(null));
            container.appendChild(skipBtn);
        }
    }

    renderWitchOptions(container, extra) {
        const { wolf_target, can_save, can_poison } = extra || {};

        if (can_save && wolf_target !== null && wolf_target !== undefined) {
            const targetPlayer = this.players.find(p => p.seat === wolf_target);
            if (targetPlayer && targetPlayer.alive) {
                const saveBtn = document.createElement('button');
                saveBtn.className = 'action-btn';
                saveBtn.textContent = `使用解药救 ${wolf_target + 1}号 ${targetPlayer.name}`;
                saveBtn.addEventListener('click', () => this.selectAction({ type: 'save' }));
                container.appendChild(saveBtn);
            }
        }

        if (can_poison) {
            const poisonLabel = document.createElement('div');
            poisonLabel.style.cssText = 'width:100%;text-align:center;margin:10px 0 5px;color:var(--accent-red)';
            poisonLabel.textContent = '使用毒药毒杀:';
            container.appendChild(poisonLabel);

            this.players.filter(p => p.alive && p.seat !== this.mySeat).forEach(player => {
                const btn = document.createElement('button');
                btn.className = 'action-btn danger';
                btn.textContent = `${player.seat + 1}号 ${player.name}`;
                btn.addEventListener('click', () => this.selectAction({ type: 'poison', target: player.seat }));
                container.appendChild(btn);
            });
        }

        const passBtn = document.createElement('button');
        passBtn.className = 'action-btn';
        passBtn.textContent = '不使用药水';
        passBtn.addEventListener('click', () => this.selectAction({ type: 'pass' }));
        container.appendChild(passBtn);
    }

    selectAction(data) {
        if (!this.pendingAction) return;
        if (this._countdownTimer) {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        }
        this.ws.send(JSON.stringify({
            type: 'action',
            action_type: this.pendingAction.action_type,
            data: data
        }));
        document.getElementById('action-panel').style.display = 'none';
        this.pendingAction = null;
    }

    submitSpeech() {
        const input = document.getElementById('speech-input');
        const speech = input.value.trim();
        if (!speech) {
            alert('请输入发言内容');
            return;
        }
        this.selectAction(speech);
        input.value = '';
    }

    handleGameEnd(data) {
        this.showLoading(false);

        const winnerText = document.getElementById('winner-text');
        winnerText.textContent = `${data.winner_text}获胜！`;
        winnerText.className = data.winner === 'village' ? 'village' : 'wolf';

        const playersList = document.getElementById('final-players');
        playersList.innerHTML = data.players.map(p => `
            <div class="final-player-card ${p.role === 'Werewolf' ? 'wolf' : 'village'}">
                <div class="player-name">${p.seat + 1}号 ${p.name}</div>
                <div class="player-role ${p.role === 'Werewolf' ? 'wolf' : 'village'}">${p.role_text}</div>
                <div class="player-status ${p.alive ? '' : 'dead'}">${p.alive ? '存活' : '死亡'}</div>
            </div>
        `).join('');

        this.showScreen('game-end-screen');
    }

    restartGame() {
        if (this.isOwner) {
            this.ws.send(JSON.stringify({ type: 'restart_game' }));
        } else {
            this.mySeat = null;
            this.myRole = null;
            this.players = [];
            this.gameStarted = false;
            this.isSpectator = false;
            document.getElementById('messages').innerHTML = '';
            this.showLobby();
        }
    }

    shouldShowMessage(data) {
        const visibilityType = data.visibility_type;
        if (!visibilityType) return true;

        switch (visibilityType) {
            case 'wolf_only': return this.myRole === 'Werewolf';
            case 'guard_only': return this.myRole === 'Guard';
            case 'witch_only': return this.myRole === 'Witch';
            case 'seer_only': return this.myRole === 'Seer';
            case 'init_progress': return true;
            default: return true;
        }
    }

    // ========== UI 辅助函数 ==========

    showScreen(screenId) {
        document.querySelectorAll('.screen').forEach(screen => {
            screen.classList.remove('active');
        });
        document.getElementById(screenId).classList.add('active');
    }

    showLoading(show) {
        if (show && this.gameStarted) return;
        document.getElementById('loading-overlay').style.display = show ? 'flex' : 'none';
    }

    renderPlayers() {
        const leftList = document.getElementById('players-left-list');
        const rightList = document.getElementById('players-right-list');
        leftList.innerHTML = '';
        rightList.innerHTML = '';

        const halfCount = Math.ceil(this.players.length / 2);

        this.players.forEach((player, index) => {
            const card = this.createPlayerCard(player);
            if (index < halfCount) {
                leftList.appendChild(card);
            } else {
                rightList.appendChild(card);
            }
        });
    }

    createPlayerCard(player) {
        const card = document.createElement('div');
        card.className = 'player-card';
        card.dataset.seat = player.seat;

        if (!player.alive) card.classList.add('dead');
        const isMe = player.seat === this.mySeat;
        if (isMe) card.classList.add('is-human');

        const roleIcons = {
            'Villager': '👤',
            'Werewolf': '🐺',
            'Seer': '👁️',
            'Witch': '🧪',
            'Hunter': '🔫',
            'Guard': '🛡️'
        };

        const icon = isMe && this.myRole ? roleIcons[this.myRole] : '👤';

        card.innerHTML = `
            <div class="player-avatar">${icon}</div>
            <div class="player-info">
                <div class="player-name">${player.name}${isMe ? ' (你)' : ''}</div>
                <div class="player-seat">${player.seat + 1}号位</div>
            </div>
            <span class="player-status ${player.alive ? '' : 'dead'}">${player.alive ? '存活' : '死亡'}</span>
        `;

        return card;
    }

    updateMyRoleDisplay() {
        const roleTexts = {
            'Villager': '村民',
            'Werewolf': '狼人',
            'Seer': '预言家',
            'Witch': '女巫',
            'Hunter': '猎人',
            'Guard': '守卫'
        };
        document.getElementById('my-role-display').textContent = roleTexts[this.myRole] || this.myRole;
    }

    updateAliveCount() {
        const aliveCount = this.players.filter(p => p.alive).length;
        document.getElementById('alive-count').textContent = `存活: ${aliveCount}人`;
    }

    addSystemMessage(text, important = false, isDeath = false) {
        const container = document.getElementById('messages');
        const message = document.createElement('div');
        message.className = 'message system' + (important ? ' important' : '') + (isDeath ? ' death' : '');
        message.innerHTML = `<div class="message-content">${text}</div>`;
        container.appendChild(message);
        this.scrollToBottom();
    }

    addSpeechMessage(seat, name, content, isLastWords = false) {
        const container = document.getElementById('messages');
        const player = this.players.find(p => p.seat === seat);
        const isMe = seat === this.mySeat;
        const isWolf = isMe && this.myRole === 'Werewolf';

        const message = document.createElement('div');
        message.className = 'message speech' + (isWolf ? ' wolf' : '') + (isLastWords ? ' last-words' : '');

        const roleIcons = {
            'Villager': '👤',
            'Werewolf': '🐺',
            'Seer': '👁️',
            'Witch': '🧪',
            'Hunter': '🔫',
            'Guard': '🛡️'
        };

        const icon = isMe && this.myRole ? roleIcons[this.myRole] : '👤';

        message.innerHTML = `
            <div class="message-header">
                <div class="message-avatar">${icon}</div>
                <span class="message-sender">${seat + 1}号 ${name}${isLastWords ? ' (遗言)' : ''}</span>
            </div>
            <div class="message-text">${this.escapeHtml(content)}</div>
        `;

        container.appendChild(message);
        this.scrollToBottom();
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    scrollToBottom() {
        const container = document.getElementById('messages');
        setTimeout(() => container.scrollTop = container.scrollHeight, 100);
    }
}

// 初始化游戏
const game = new WolfChaGame();
