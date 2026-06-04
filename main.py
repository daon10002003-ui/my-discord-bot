import discord
from discord.ext import commands
from discord import app_commands
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import json
import os

# --- 設定項目 ---
OKEN = os.getenv("DISCORD_TOKEN")
# ---------------

# レンダーでのファイル書き込みエラーを防ぐため、データはメモリ上に一時保存（再起動でリセットされますが安全に動きます）
_VENDING_DATA = {
    "config": {
        "title": "🛒 自動自販機パネル",
        "description": "下のボタンを押すと商品を購入（引き換え）できます。\n商品はDMですぐに届きます。",
        "image_url": "",
        "proof_channel_id": None
    },
    "items": {}
}

# ★Renderの強制終了を防ぐための常時起動用Webサーバー
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write("Bot is running!".encode("utf-8"))

def run_web_server():
    server = HTTPServer(('0.0.0.0', 8080), KeepAliveHandler)
    server.serve_forever()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

# --- 購入用のボタン処理 ---
class VendingButton(discord.ui.Button):
    def __init__(self, item_name: str):
        super().__init__(label=f"{item_name}を購入🎁", style=discord.ButtonStyle.green, custom_id=f"buy_{item_name}")
        self.item_name = item_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        global _VENDING_DATA
        
        # 在庫チェック
        if self.item_name not in _VENDING_DATA["items"] or not _VENDING_DATA["items"][self.item_name]:
            await interaction.followup.send(f"申し訳ありません、**{self.item_name}** は現在売り切れです。", ephemeral=True)
            return

        stock_list = _VENDING_DATA["items"][self.item_name]
        purchased_product = stock_list[0]

        # 【無限機能】頭に「無限:」がついているか判定
        is_infinite = purchased_product.startswith("無限:")

        if is_infinite:
            display_product = purchased_product.replace("無限:", "", 1)
        else:
            display_product = stock_list.pop(0)

        # 購入メッセージの作成
        success_embed = discord.Embed(
            title="🎁 商品の受け取り成功！",
            description=f"あなた専用の商品内容です。\n\n**【商品名】** {self.item_name}\n\n**【内容】**\n{display_product}",
            color=discord.Color.green()
        )

        try:
            # 購入者のDMに送信
            await interaction.user.send(embed=success_embed)
            
            # 実績記入案内
            proof_id = _VENDING_DATA["config"].get("proof_channel_id")
            if proof_id:
                proof_channel = interaction.guild.get_channel(int(proof_id))
                if proof_channel:
                    await interaction.user.send(f"✍️ ぜひ {proof_channel.mention} に実績の記入をお願いします！")
        except discord.Forbidden:
            # DMが閉じている場合は画面にだけ出す
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            await interaction.followup.send("⚠️ DMが閉じられているため、画面上のみの表示となります。メモ等にお控えください。", ephemeral=True)
            
            # 通常在庫でDM失敗した場合は在庫を元に戻す
            if not is_infinite:
                stock_list.insert(0, purchased_product)
            return

        # 実績ログの送信先判定
        target_channel = interaction.channel
        proof_id = _VENDING_DATA["config"].get("proof_channel_id")
        if proof_id:
            chan = interaction.guild.get_channel(int(proof_id))
            if chan:
                target_channel = chan

        user = interaction.user
        log_text = (
            f"🎉 **購入者:** {user.mention}\n"
            f"👤 **ユーザー名:** `{user.name}`\n"
            f"🆔 **ユーザーID:** `{user.id}`\n\n"
            f"📦 **購入商品:** **{self.item_name}** を購入（受け取り）しました！"
        )

        buy_embed = discord.Embed(title="✅ 規約・購入実績", description=log_text, color=discord.Color.green())
        await target_channel.send(embed=buy_embed)

class VendingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        global _VENDING_DATA
        for item_name in _VENDING_DATA["items"].keys():
            self.add_item(VendingButton(item_name))

# --- 管理リモコン（/自販機設定 のポップアップ用） ---
class ConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="📦 在庫追加", style=discord.ButtonStyle.blurple, row=0)
    async def add_stock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class AddStockModal(discord.ui.Modal, title="在庫の追加"):
            item_name = discord.ui.TextInput(label="商品名（例: ラマロット）", placeholder="商品名を入力してください")
            stock_content = discord.ui.TextInput(
                label="中身（無限にする場合は先頭に「無限:」）", 
                style=discord.TextStyle.paragraph, 
                placeholder="例：無限:https://mediafire.com/... （無限在庫になります）"
            )
            async def on_submit(self, idx: discord.Interaction):
                global _VENDING_DATA
                if self.item_name.value not in _VENDING_DATA["items"]:
                    _VENDING_DATA["items"][self.item_name.value] = []
                _VENDING_DATA["items"][self.item_name.value].append(self.stock_content.value)
                await idx.response.send_message(f"📥 **{self.item_name.value}** に在庫を追加しました！", ephemeral=True)
        await interaction.response.send_modal(AddStockModal())

    @discord.ui.button(label="🗑️ 在庫削除（商品削除）", style=discord.ButtonStyle.danger, row=0)
    async def del_item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class DelItemModal(discord.ui.Modal, title="商品の削除"):
            item_name = discord.ui.TextInput(label="削除したい商品名", placeholder="完全に消去する商品名を入力")
            async def on_submit(self, idx: discord.Interaction):
                global _VENDING_DATA
                if self.item_name.value in _VENDING_DATA["items"]:
                    del _VENDING_DATA["items"][self.item_name.value]
                    await idx.response.send_message(f"🗑️ **{self.item_name.value}** を完全に削除しました。", ephemeral=True)
                else:
                    await idx.response.send_message("❌ その商品名は見つかりませんでした。", ephemeral=True)
        await interaction.response.send_modal(DelItemModal())

    @discord.ui.button(label="📝 タイトル等設定", style=discord.ButtonStyle.secondary, row=1)
    async def set_title_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class TitleModal(discord.ui.Modal, title="タイトルの変更"):
            title = discord.ui.TextInput(label="パネルのタイトル", placeholder="例: 🛒 自動自販機パネル")
            async def on_submit(self, idx: discord.Interaction):
                global _VENDING_DATA
                _VENDING_DATA["config"]["title"] = self.title.value
                await idx.response.send_message("✏️ タイトルを更新しました！パネルを再作成すると反映されます。", ephemeral=True)
        await interaction.response.send_modal(TitleModal())

    @discord.ui.button(label="📄 パネル説明文", style=discord.ButtonStyle.secondary, row=1)
    async def set_desc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class DescModal(discord.ui.Modal, title="説明文の変更"):
            desc = discord.ui.TextInput(label="パネルの説明文", style=discord.TextStyle.paragraph, placeholder="説明文を入力してください")
            async def on_submit(self, idx: discord.Interaction):
                global _VENDING_DATA
                _VENDING_DATA["config"]["description"] = self.desc.value
                await idx.response.send_message("✏️ 説明文を更新しました！パネルを再作成すると反映されます。", ephemeral=True)
        await interaction.response.send_modal(DescModal())

    @discord.ui.button(label="🖼️ 画像設定", style=discord.ButtonStyle.secondary, row=2)
    async def set_image_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ImageModal(discord.ui.Modal, title="画像URLの設定"):
            url = discord.ui.TextInput(label="画像のURL", placeholder="https://から始まるリンク（空欄で消去）", required=False)
            async def on_submit(self, idx: discord.Interaction):
                global _VENDING_DATA
                _VENDING_DATA["config"]["image_url"] = self.url.value
                await idx.response.send_message("🖼️ 画像設定を更新しました！パネルを再作成すると反映されます。", ephemeral=True)
        await interaction.response.send_modal(ImageModal())

    @discord.ui.button(label="⭐ 実績記入設定", style=discord.ButtonStyle.secondary, row=2)
    async def set_proof_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ProofModal(discord.ui.Modal, title="実績チャンネルの設定"):
            channel_id = discord.ui.TextInput(label="チャンネルID（数字のみ）", placeholder="例: 1511448796964454421", required=False)
            async def on_submit(self, idx: discord.Interaction):
                global _VENDING_DATA
                if self.channel_id.value:
                    _VENDING_DATA["config"]["proof_channel_id"] = self.channel_id.value
                    await idx.response.send_message("⭐ 実績ログの送信先と実績案内を設定しました！", ephemeral=True)
                else:
                    _VENDING_DATA["config"]["proof_channel_id"] = None
                    await idx.response.send_message("⭐ 実績ログをオフにしました。", ephemeral=True)
        await interaction.response.send_modal(ProofModal())

# --- コマンド登録 ---

# 1. /自販機設定
@bot.tree.command(name="自販機設定", description="自販機の在庫管理やパネルの設定メニューを開きます")
@app_commands.default_permissions(administrator=True)
async def config_vending(interaction: discord.Interaction):
    view = ConfigView()
    embed = discord.Embed(
        title="🔧 自販機 管理・設定メニュー",
        description="下のボタンを押して、在庫の追加やパネルの文字・画像を変更してください。\n※あなた（管理者）にしか見えません。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# 2. /自販機作成
@bot.tree.command(name="自販機作成", description="最新の設定で自販機パネルをこのチャンネルに設置します")
@app_commands.default_permissions(administrator=True)
async def create_vending(interaction: discord.Interaction):
    await interaction.response.send_message("⚙️ 自販機パネルを設置しました！", ephemeral=True)
    
    global _VENDING_DATA
    view = VendingView()
    
    embed = discord.Embed(
        title=_VENDING_DATA["config"]["title"],
        description=_VENDING_DATA["config"]["description"],
        color=discord.Color.green()
    )
    
    if _VENDING_DATA["items"]:
        for item, stocks in _VENDING_DATA["items"].items():
            if stocks and stocks[0].startswith("無限:"):
                embed.add_field(name=item, value="在庫数: `無限`", inline=False)
            else:
                embed.add_field(name=item, value=f"在庫数: `{len(stocks)}`", inline=False)
    else:
        embed.description += "\n\n※商品が未登録です。`/自販機設定` から追加してください。"

    if _VENDING_DATA["config"].get("image_url"):
        embed.set_image(url=_VENDING_DATA["config"]["image_url"])

    await interaction.channel.send(embed=embed, view=view)


@bot.event
async def on_ready():
    bot.add_view(VendingView())
    print(f"ログインしました: {bot.user.name}")

# Webサーバーを別スレッドで起動してからBOTを起動
threading.Thread(target=run_web_server, daemon=True).start()
bot.run(TOKEN)
