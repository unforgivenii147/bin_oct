#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path

PLUGIN_PATTERNS = {
    "lazy.nvim": [
        r"lazy\.setup",
        r"lazy\.nvim",
        r'require\(["\']lazy["\']',
        r"\blazy\b",
    ],
    "packer.nvim": [
        r"packer\.setup",
        r"packer\.nvim",
        r'require\(["\']packer["\']',
        r"\bpacker\b",
    ],
    "vim-plug": [r"vim-plug", r"plug#begin", r'\bPlug\s+["\']'],
    "telescope": [r"telescope", r'require\(["\']telescope["\']', r"telescope\.setup"],
    "fzf-lua": [r"fzf-lua", r"fzf_lua", r'require\(["\']fzf-lua["\']'],
    "treesitter": [
        r"treesitter",
        r"nvim-treesitter",
        r"tree-sitter",
        r'require\(["\']nvim-treesitter["\']',
    ],
    "lualine": [r"lualine", r'require\(["\']lualine["\']', r"lualine\.setup"],
    "bufferline": [r"bufferline", r"buffer-line", r'require\(["\']bufferline["\']'],
    "statuscol": [r"statuscol", r"status-column", r'require\(["\']statuscol["\']'],
    "indent-blankline": [
        r"indent-blankline",
        r"indent_blankline",
        r"ibl\.setup",
        r'require\(["\']ibl["\']',
    ],
    "mini.nvim": [r"mini\.", r'require\(["\']mini\.'],
    "noice": [r"noice", r'require\(["\']noice["\']', r"noice\.setup"],
    "notify": [r"nvim-notify", r"notify\.setup", r'require\(["\']notify["\']'],
    "dressing": [r"dressing", r"dressing\.setup", r'require\(["\']dressing["\']'],
    "dashboard": [
        r"dashboard-nvim",
        r"dashboard\.setup",
        r'require\(["\']dashboard["\']',
    ],
    "alpha": [r"alpha-nvim", r"alpha\.setup", r'require\(["\']alpha["\']'],
    "which-key": [
        r"which-key",
        r"which_key",
        r"whichkey",
        r'require\(["\']which-key["\']',
    ],
    "legendary": [r"legendary", r"legendary\.setup", r'require\(["\']legendary["\']'],
    "nvim-cmp": [
        r"nvim-cmp",
        r"nvim_cmp",
        r"cmp\.setup",
        r'require\(["\']cmp["\']',
        r'require\(["\']cmp_nvim',
    ],
    "lspconfig": [r"lspconfig", r"nvim-lspconfig", r'require\(["\']lspconfig["\']'],
    "mason": [
        r"mason",
        r"mason-nvim",
        r"mason-lspconfig",
        r"mason\.setup",
        r'require\(["\']mason["\']',
    ],
    "mason-lspconfig": [
        r"mason-lspconfig",
        r"mason_lspconfig",
        r'require\(["\']mason-lspconfig["\']',
    ],
    "mason-tool-installer": [
        r"mason-tool-installer",
        r"mason_tool_installer",
        r'require\(["\']mason-tool-installer["\']',
    ],
    "null-ls": [r"null-ls", r"null_ls", r'require\(["\']null-ls["\']'],
    "none-ls": [r"none-ls", r"none_ls", r'require\(["\']none-ls["\']'],
    "conform": [r"conform", r"conform\.setup", r'require\(["\']conform["\']'],
    "efm-langserver": [r"efm-langserver", r"efm\.setup", r'require\(["\']efm["\']'],
    "fidget": [r"fidget", r"fidget\.setup", r'require\(["\']fidget["\']'],
    "lsp-status": [r"lsp-status", r"lsp_status", r'require\(["\']lsp-status["\']'],
    "lsp-signature": [
        r"lsp-signature",
        r"lsp_signature",
        r'require\(["\']lsp_signature["\']',
    ],
    "lsp-lines": [r"lsp-lines", r"lsp_lines", r'require\(["\']lsp_lines["\']'],
    "goto-preview": [
        r"goto-preview",
        r"goto_preview",
        r'require\(["\']goto-preview["\']',
    ],
    "lspsaga": [r"lspsaga", r"lspsaga\.setup", r'require\(["\']lspsaga["\']'],
    "lsp-ui": [r"lsp-ui", r"lsp_ui", r'require\(["\']lspconfig["\'].*lsp-ui'],
    "luasnip": [r"luasnip", r"lua-snip", r'require\(["\']luasnip["\']', r"ls\.setup"],
    "snippy": [r"snippy", r"snippy\.setup", r'require\(["\']snippy["\']'],
    "ultisnips": [r"ultisnips", r"UltiSnips", r"ultisnips#"],
    "friendly-snippets": [
        r"friendly-snippets",
        r"friendly_snippets",
        r'require\(["\']friendly-snippets["\']',
    ],
    "gitsigns": [r"gitsigns", r"gitsigns\.setup", r'require\(["\']gitsigns["\']'],
    "neogit": [r"neogit", r"neogit\.setup", r'require\(["\']neogit["\']'],
    "vim-fugitive": [r"vim-fugitive", r"fugitive", r":Git\b"],
    "git-blame": [r"git-blame", r"git_blame", r"gitblame"],
    "gitlinker": [r"gitlinker", r"git-linker", r'require\(["\']gitlinker["\']'],
    "diffview": [r"diffview", r"diffview\.setup", r'require\(["\']diffview["\']'],
    "octo": [r"octo\.nvim", r"octo\.setup", r'require\(["\']octo["\']'],
    "git-conflict": [r"git-conflict", r"git_conflict", r"git-conflict\.setup"],
    "neo-tree": [r"neo-tree", r"neo_tree", r"neotree", r'require\(["\']neo-tree["\']'],
    "nvim-tree": [
        r"nvim-tree",
        r"nvim_tree",
        r'require\(["\']nvim-tree["\']',
        r"nvim-tree\.setup",
    ],
    "oil": [r"oil\.setup", r"oil\.nvim", r'require\(["\']oil["\']', r"\boil\b"],
    "chad-tree": [r"chad-tree", r"chad_tree", r'require\(["\']nvchad'],
    "harpoon": [
        r"harpoon",
        r"harpoon2",
        r'require\(["\']harpoon["\']',
        r"harpoon\.setup",
    ],
    "hop": [r"hop\.setup", r"hop\.nvim", r'require\(["\']hop["\']'],
    "leap": [r"leap\.setup", r"leap\.nvim", r'require\(["\']leap["\']'],
    "flash": [r"flash\.setup", r"flash\.nvim", r'require\(["\']flash["\']'],
    "easymotion": [r"easymotion", r"easy-motion", r"vim-easymotion"],
    "marks": [r"marks\.setup", r"marks\.nvim", r'require\(["\']marks["\']'],
    "grapple": [r"grapple", r"grapple\.setup", r'require\(["\']grapple["\']'],
    "arrow": [r"arrow\.setup", r"arrow\.nvim", r'require\(["\']arrow["\']'],
    "surround": [
        r"nvim-surround",
        r"surround\.setup",
        r'require\(["\']nvim-surround["\']',
    ],
    "autopairs": [
        r"nvim-autopairs",
        r"autopairs\.setup",
        r'require\(["\']nvim-autopairs["\']',
    ],
    "comment": [
        r"comment\.setup",
        r"nvim-comment",
        r"Comment\.setup",
        r'require\(["\']Comment["\']',
    ],
    "ts-comments": [r"ts-comments", r"ts_comments", r'require\(["\']ts-comments["\']'],
    "tcomment": [r"tcomment", r"t-comment", r"vim-tcomment"],
    "vim-commentary": [r"vim-commentary", r"commentary"],
    "dial": [r"dial\.setup", r"dial\.nvim", r'require\(["\']dial["\']'],
    "substitute": [
        r"substitute\.setup",
        r"substitute\.nvim",
        r'require\(["\']substitute["\']',
    ],
    "ultimate-autopair": [r"ultimate-autopair", r"ultimate_autopair"],
    "vim-visual-multi": [r"vim-visual-multi", r"visual-multi", r"visual_multi"],
    "vim-illuminate": [r"illuminate", r"vim-illuminate", r"illuminate\.setup"],
    "todo-comments": [
        r"todo-comments",
        r"todo_comments",
        r"todocomments",
        r'require\(["\']todo-comments["\']',
    ],
    "twilight": [r"twilight\.setup", r"twilight\.nvim", r'require\(["\']twilight["\']'],
    "zen-mode": [
        r"zen-mode",
        r"zen_mode",
        r'require\(["\']zen-mode["\']',
        r"zen-mode\.setup",
    ],
    "true-zen": [r"true-zen", r"true_zen", r'require\(["\']true-zen["\']'],
    "colorizer": [r"colorizer", r"nvim-colorizer", r"colorizer\.setup"],
    "highlight-colors": [
        r"highlight-colors",
        r"highlight_colors",
        r"highlight-colors\.setup",
    ],
    "vim-hexokinase": [r"hexokinase", r"vim-hexokinase"],
    "dap": [r"nvim-dap", r"dap\.setup", r'require\(["\']dap["\']', r"\bdap\b"],
    "dap-ui": [r"dap-ui", r"dapui", r"dap_ui", r'require\(["\']dapui["\']'],
    "dap-python": [r"dap-python", r"dap_python", r'require\(["\']dap-python["\']'],
    "dap-go": [r"dap-go", r"dap_go", r'require\(["\']dap-go["\']'],
    "nvim-dap-virtual-text": [
        r"dap-virtual-text",
        r"dap_virtual_text",
        r"nvim-dap-virtual-text",
    ],
    "neotest": [r"neotest", r"neotest\.setup", r'require\(["\']neotest["\']'],
    "vim-test": [r"vim-test", r"vim_test", r"vim-test#"],
    "plenary": [r"plenary", r'require\(["\']plenary["\']'],
    "toggleterm": [
        r"toggleterm",
        r"toggle-term",
        r"toggleterm\.setup",
        r'require\(["\']toggleterm["\']',
    ],
    "floaterm": [r"floaterm", r"float-term", r"floaterm#"],
    "FTerm": [r"FTerm\.setup", r"ft-nvim", r'require\(["\']FTerm["\']'],
    "auto-session": [r"auto-session", r"auto_session", r"auto-session\.setup"],
    "persistence": [
        r"persistence\.setup",
        r"persistence\.nvim",
        r'require\(["\']persistence["\']',
    ],
    "project": [
        r"project\.nvim",
        r"project\.setup",
        r'require\(["\']project_nvim["\']',
    ],
    "telescope-project": [
        r"telescope-project",
        r"telescope_project",
        r"telescope._extensions.project",
    ],
    "trouble": [r"trouble", r"trouble\.setup", r'require\(["\']trouble["\']'],
    "spectre": [r"spectre", r"spectre\.setup", r'require\(["\']spectre["\']'],
    "nvim-bqf": [r"bnf", r"nvim-bqf", r"bqf\.setup"],
    "vim-ripgrep": [r"vim-ripgrep", r"Ripgrep", r"ripgrep#"],
    "tagbar": [r"tagbar", r"tag-bar", r"tagbar#"],
    "vista": [r"vista", r"vista\.setup", r"vista#"],
    "symbols-outline": [
        r"symbols-outline",
        r"symbols_outline",
        r"symbols-outline\.setup",
    ],
    "aerial": [r"aerial\.setup", r"aerial\.nvim", r'require\(["\']aerial["\']'],
    "vim-dadbod": [r"vim-dadbod", r"dadbod", r"dadbod#"],
    "dadbod-ui": [r"dadbod-ui", r"dadbod_ui", r"dadbod-ui\.setup"],
    "sqlite": [r"sqlite\.lua", r"sqlite", r'require\(["\']sqlite["\']'],
    "vim-go": [r"vim-go", r"vim_go", r"\bgo#"],
    "rust-tools": [r"rust-tools", r"rust_tools", r"rust-tools\.setup"],
    "rustaceanvim": [
        r"rustaceanvim",
        r"rustacean\.setup",
        r'require\(["\']rustaceanvim["\']',
    ],
    "vim-python": [r"vim-python", r"python-mode", r"python-syntax"],
    "vim-javascript": [r"vim-javascript", r"javascript\.vim", r"vim-js"],
    "typescript-tools": [
        r"typescript-tools",
        r"typescript\.tools",
        r"typescript-tools\.setup",
    ],
    "vim-vue": [r"vim-vue", r"vim_vue", r"vue\.vim"],
    "vim-react": [r"vim-react", r"vim_react", r"vim-jsx"],
    "vim-markdown": [r"vim-markdown", r"markdown\.vim", r"vim_markdown"],
    "markdown-preview": [
        r"markdown-preview",
        r"markdown_preview",
        r"markdown-preview\.setup",
    ],
    "vim-tex": [r"vim-tex", r"vimtex", r"latex"],
    "vim-julia": [r"vim-julia", r"julia-vim", r"julia\.vim"],
    "vim-r": [r"vim-r", r"vim_r", r"Nvim-R"],
    "vim-scala": [r"vim-scala", r"scala-vim", r"scala\.vim"],
    "undo-tree": [r"undo-tree", r"undo_tree", r"undotree", r"undo-tree\.setup"],
    "whichkey": [r"whichkey", r"which-key", r"which_key"],
    "vim-repeat": [r"vim-repeat", r"vim_repeat", r"repeat\.vim"],
    "vim-surround": [r"vim-surround", r"vim_surround", r"surround\.vim"],
    "vim-unimpaired": [r"vim-unimpaired", r"unimpaired", r"unimpaired\.vim"],
    "vim-abolish": [r"vim-abolish", r"abolish", r"abolish\.vim"],
    "vim-speeddating": [r"vim-speeddating", r"speeddating", r"speeddating\.vim"],
    "vim-exchange": [r"vim-exchange", r"exchange", r"exchange\.vim"],
    "vim-characterize": [r"vim-characterize", r"characterize", r"characterize\.vim"],
    "vim-textobj": [r"vim-textobj", r"textobj", r"textobj-"],
    "nvim-treesitter-textobjects": [
        r"treesitter-textobjects",
        r"textobjects\.setup",
        r'require\(["\']nvim-treesitter-textobjects["\']',
    ],
    "splitjoin": [r"splitjoin", r"split-join", r"splitjoin\.vim"],
    "vim-sort": [r"vim-sort", r"sort\.vim", r"\bsort#"],
    "vim-easy-align": [
        r"vim-easy-align",
        r"easy-align",
        r"easy_align",
        r"easy-align\.setup",
    ],
    "tabular": [r"tabular", r"tabular#", r"tabular\.vim"],
    "vim-argwrap": [r"vim-argwrap", r"argwrap", r"argwrap\.vim"],
    "prettier": [r"prettier", r"prettier\.setup", r"vim-prettier", r"prettier-nvim"],
    "eslint": [r"eslint", r"eslint\.setup", r"vim-eslint", r"eslint-nvim"],
    "stylelint": [r"stylelint", r"stylelint\.setup", r"vim-stylelint"],
    "ale": [r"\bale\b", r"ale\.vim", r"ale#", r"vim-ale"],
    "vim-lint": [r"vim-lint", r"vim_lint", r"lint\.vim"],
    "nvim-web-devicons": [
        r"nvim-web-devicons",
        r"web-devicons",
        r"devicons\.setup",
        r'require\(["\']nvim-web-devicons["\']',
    ],
    "lspkind": [
        r"lspkind",
        r"lsp-kind",
        r"lspkind\.setup",
        r'require\(["\']lspkind["\']',
    ],
    "vim-devicons": [r"vim-devicons", r"vim_devicons", r"devicons"],
    "nerd-fonts": [r"nerd-fonts", r"nerd_fonts", r"nerdfonts"],
    "tokyonight": [
        r"tokyonight",
        r"tokyo-night",
        r"tokyonight\.setup",
        r"tokyonight\.load",
    ],
    "catppuccin": [r"catppuccin", r"catppuccin\.setup", r"catppuccin\.load"],
    "onedark": [r"onedark", r"one-dark", r"onedark\.setup", r"onedark\.load"],
    "gruvbox": [r"gruvbox", r"gruvbox\.setup", r"gruvbox\.load"],
    "nord": [r"nord", r"nord\.setup", r"nord\.load"],
    "rose-pine": [r"rose-pine", r"rose_pine", r"rose-pine\.setup", r"rose-pine\.load"],
    "kanagawa": [r"kanagawa", r"kanagawa\.setup", r"kanagawa\.load"],
    "github-theme": [r"github-theme", r"github_theme", r"github-theme\.setup"],
    "dracula": [r"dracula", r"dracula\.setup", r"dracula\.load"],
    "everforest": [r"everforest", r"ever-forest", r"everforest\.setup"],
    "material": [r"material\.setup", r"material\.load", r"material-theme"],
    "nightfox": [r"nightfox", r"night-fox", r"nightfox\.setup"],
    "ayu": [r"ayu", r"ayu-vim", r"ayu\.setup"],
    "solarized": [r"solarized", r"solarized\.setup", r"solarized\.load"],
    "melange": [r"melange", r"melange\.setup", r"melange\.load"],
    "vim-colorschemes": [r"vim-colorschemes", r"colorschemes", r"vim_colorschemes"],
    "impatient": [r"impatient", r"impatient\.setup", r"impatient\.nvim"],
    "vim-startuptime": [r"vim-startuptime", r"startuptime", r"vim_startuptime"],
    "profile": [r"profile\.nvim", r"profile\.setup", r'require\(["\']profile["\']'],
    "vim-which-key": [r"vim-which-key", r"vim_which_key", r"vim-whichkey"],
    "keys": [r"keys\.setup", r"keys\.nvim", r'require\(["\']keys["\']'],
    "cheatsheet": [r"cheatsheet", r"cheat-sheet", r"cheat\.setup"],
    "vim-help": [r"vim-help", r"help\.vim", r"vim_help"],
    "vim-tmux": [r"vim-tmux", r"tmux\.vim", r"vim_tmux", r"tmux-navigator"],
    "tmux-navigator": [r"tmux-navigator", r"tmux_navigator", r"tmux-navigator\.setup"],
    "vim-tmux-navigator": [r"vim-tmux-navigator", r"vim_tmux_navigator"],
    "window-picker": [r"window-picker", r"window_picker", r"window-picker\.setup"],
    "winshift": [r"winshift", r"win-shift", r"winshift\.setup"],
    "vim-maximizer": [r"vim-maximizer", r"vim_maximizer", r"maximizer\.vim"],
    "zen-mode": [r"zen-mode", r"zen_mode", r"zen-mode\.setup"],
    "focus": [r"focus\.nvim", r"focus\.setup", r'require\(["\']focus["\']'],
    "scrollbar": [r"scrollbar", r"scroll-bar", r"scrollbar\.setup"],
    "nvim-scrollview": [r"nvim-scrollview", r"scrollview", r"scrollview\.setup"],
    "smoothscroll": [r"smoothscroll", r"smooth-scroll", r"smooth-scroll\.setup"],
    "neoscroll": [r"neoscroll", r"neo-scroll", r"neoscroll\.setup"],
    "vim-smoothie": [r"vim-smoothie", r"smoothie", r"smoothie\.vim"],
    "vim-remote": [r"vim-remote", r"remote\.vim", r"vim_remote"],
    "netrw": [r"netrw", r"netrw\.vim", r"netrw#"],
    "vim-ssh": [r"vim-ssh", r"ssh\.vim", r"vim_ssh"],
    "vim-scp": [r"vim-scp", r"scp\.vim", r"vim_scp"],
    "vim-obsession": [r"vim-obsession", r"obsession", r"obsession\.vim"],
    "vim-startify": [r"vim-startify", r"startify", r"startify#"],
    "vim-devicons": [r"vim-devicons", r"vim_devicons", r"devicons\.vim"],
    "vim-projectionist": [r"vim-projectionist", r"projectionist", r"projectionist#"],
    "vim-dispatch": [r"vim-dispatch", r"dispatch\.vim", r"dispatch#"],
    "vim-eunuch": [r"vim-eunuch", r"eunuch", r"eunuch\.vim"],
    "vim-rails": [r"vim-rails", r"rails\.vim", r"vim_rails"],
    "vim-ruby": [r"vim-ruby", r"ruby\.vim", r"vim_ruby"],
    "vim-elixir": [r"vim-elixir", r"elixir\.vim", r"vim_elixir"],
    "vim-clojure": [r"vim-clojure", r"clojure\.vim", r"vim_clojure"],
    "vim-haskell": [r"vim-haskell", r"haskell\.vim", r"vim_haskell"],
    "vim-lua": [r"vim-lua", r"lua\.vim", r"vim_lua"],
    "vim-rust": [r"vim-rust", r"rust\.vim", r"vim_rust"],
    "vim-crystal": [r"vim-crystal", r"crystal\.vim", r"vim_crystal"],
    "vim-nim": [r"vim-nim", r"nim\.vim", r"vim_nim"],
    "vim-zig": [r"vim-zig", r"zig\.vim", r"vim_zig"],
    "vim-dart": [r"vim-dart", r"dart\.vim", r"vim_dart"],
    "vim-flutter": [r"vim-flutter", r"flutter\.vim", r"vim_flutter"],
    "vim-kotlin": [r"vim-kotlin", r"kotlin\.vim", r"vim_kotlin"],
    "vim-swift": [r"vim-swift", r"swift\.vim", r"vim_swift"],
    "vim-solidity": [r"vim-solidity", r"solidity\.vim", r"vim_solidity"],
    "vim-php": [r"vim-php", r"php\.vim", r"vim_php"],
    "vim-perl": [r"vim-perl", r"perl\.vim", r"vim_perl"],
    "vim-ruby": [r"vim-ruby", r"ruby\.vim", r"vim_ruby"],
    "vim-raku": [r"vim-raku", r"raku\.vim", r"vim_raku"],
}


def detect_plugins(path):
    detected = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        filename = path.name.lower()
        for plugin_name, patterns in PLUGIN_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    detected.add(plugin_name)
                    break
            for pattern in patterns:
                if re.search(pattern, filename, re.IGNORECASE):
                    detected.add(plugin_name)
                    break
    except Exception as e:
        print(f"Error reading {path}: {e}")
    return detected


def organize_files(dry_run=False):
    current_dir = Path.cwd()
    lua_files = list(current_dir.rglob("*.lua"))
    if not lua_files:
        print("No .lua files found in the current directory tree.")
        return
    print(f"Found {len(lua_files)} .lua files")
    print("Scanning for plugin references...\n")
    plugin_files = defaultdict(list)
    unclassified_files = []
    for lua_file in lua_files:
        plugins = detect_plugins(lua_file)
        if plugins:
            for plugin in plugins:
                plugin_files[plugin].append(lua_file)
            print(
                f"  {lua_file.relative_to(current_dir)}: {', '.join(sorted(plugins))}"
            )
        else:
            unclassified_files.append(lua_file)
            print(f"  {lua_file.relative_to(current_dir)}: No plugins detected")
    print("\n" + "=" * 40)
    print("Organization Plan:")
    print("=" * 40)
    for plugin in sorted(plugin_files.keys()):
        files = plugin_files[plugin]
        print(f"\n📁 {plugin}/ ({len(files)} files)")
        for file in files:
            print(f"  → {file.relative_to(current_dir)}")
    if unclassified_files:
        print(f"\n📁 unclassified/ ({len(unclassified_files)} files)")
        for file in unclassified_files:
            print(f"  → {file.relative_to(current_dir)}")
    if dry_run:
        print(
            "\n[DRY RUN] No files were moved. Run without --dry-run to organize files."
        )
        return
    response = input("\nProceed with moving files? (y/N): ").strip().lower()
    if response not in ["y", "yes"]:
        print("Operation cancelled.")
        return
    print("\nMoving files...")
    moved_count = 0
    for plugin, files in plugin_files.items():
        plugin_folder = current_dir / plugin
        plugin_folder.mkdir(exist_ok=True)
        for file in files:
            try:
                destination = plugin_folder / file.name
                if destination.exists() and destination != file:
                    stem = file.stem
                    suffix = file.suffix
                    counter = 1
                    while destination.exists():
                        new_name = f"{stem}_{counter}{suffix}"
                        destination = plugin_folder / new_name
                        counter += 1
                    print(f"  ⚠️  Name conflict: {file.name} → {destination.name}")
                shutil.move(str(file), str(destination))
                moved_count += 1
                print(
                    f"  ✓ {file.relative_to(current_dir)} → {destination.relative_to(current_dir)}"
                )
            except Exception as e:
                print(f"  ✗ Failed to move {file}: {e}")
    if unclassified_files:
        unclassified_folder = current_dir / "unclassified"
        unclassified_folder.mkdir(exist_ok=True)
        for file in unclassified_files:
            try:
                destination = unclassified_folder / file.name
                if destination.exists() and destination != file:
                    stem = file.stem
                    suffix = file.suffix
                    counter = 1
                    while destination.exists():
                        new_name = f"{stem}_{counter}{suffix}"
                        destination = unclassified_folder / new_name
                        counter += 1
                shutil.move(str(file), str(destination))
                moved_count += 1
                print(
                    f"  ✓ {file.relative_to(current_dir)} → {destination.relative_to(current_dir)}"
                )
            except Exception as e:
                print(f"  ✗ Failed to move {file}: {e}")
    print(f"\n✅ Completed! Moved {moved_count} files.")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Organize Neovim plugin files into folders by plugin name"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually moving files",
    )
    args = parser.parse_args()
    organize_files(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
