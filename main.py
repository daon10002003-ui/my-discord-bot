import discord
from discord.ext import commands
from discord import app_commands
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import os
import json

# --- 設定項目 ---
TOKEN = os.getenv("DISCORD_TOKEN")
# ---------------

DATA_FILE = "vending_machine_v3.json"

DEFAULT_DATA = {
    "config": {
        "title": "🛒 自動自販機パネル",
        "description": "下のボタンを押すと商品を購入（引き換え）できます。\n商品はDMですぐに届きます。",
        "image_url": "",
        "proof_channel_id": None
    },
    "items": {}
}

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(json.dumps(DEFAULT_DATA))

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        
    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

# --- 購入用のViewとButton ---
class VendingButton(discord.ui.Button):
    def __init__(self, item_name: str):
        super().__init__(label=f"{item_name}を購入", style=discord.ButtonStyle.green, custom_id=f"buy_{item_name}")
        self.item_name = item_name

    async def callback(self, interaction: discord.Interaction):
        data = load_data()
        
        # 在庫チェック
        if self.item_name not in data["items"] or not data["items"][self.item_name]:
            await interaction.response.send_message(f"申し訳ありません、**{self.item_name}** は現在売り切れです。", ephemeral=True)
            return

        stock_list = data["items"][self.item_name]
        purchased_product = stock_list[0] # 先頭の商品を確認

        # 【新機能】無限在庫の判定
        is_infinite = purchased_product.startswith("無限:")

        if is_infinite:
            # 「無限:」の文字を削って中身を取り出す
            display_product = purchased_product.replace("無限:", "", 1)
        else:
            # 通常在庫の場合はリストから取り出して削除
            display_product = stock_list.pop(0)
            save_data(data)

        # 購入者にDMで送信
        try:
            await interaction.user.send(
                f"🛍️ **ご購入ありがとうございます！**\n"
                f"**商品名:** {self.item_name}\n"
                f"**中身:**\n"
                f"```{display_product}```"
            )
            await interaction.response.send_message("📥 DMで商品をお送りしました！ご確認ください。", ephemeral=True)
            
            # 実績記入の設定がある場合
            proof_id = data["config"].get("proof_channel_id")
            if proof_id:
                proof_channel = bot.get_channel(int(proof_id))
                if proof_channel:
                    proof_embed = discord.Embed(
                        title="✅ 規約・購入実績",
                        description=f"{interaction.user.mention} 様が **{self.item_name}** を購入しました！\nレビューの記入にご協力をお願いします！",
                        color=discord.Color.green()
                    )
                    await proof_channel.send(embed=proof_embed)

        except discord.Forbidden:
            # DMが閉じていた場合で、通常在庫なら元に戻す
            if not is_infinite:
                stock_list.insert(0, purchased_product)
                save_data(data)
            await interaction.response.send_message("❌ DMを送信できませんでした。Discordの設定で「サーバーからのプライベートメッセージを許可する」をONにしてから再度お試しください。", ephemeral=True)

class VendingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        data = load_data()
        for item_name in data["items"].keys():
            self.add_item(VendingButton(item_name))

# --- 設定メニュー用のViewとボタン ---
class ConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="📦 在庫追加", style=discord.ButtonStyle.blurple, row=0)
    async def add_stock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class AddStockModal(discord.ui.Modal, title="在庫の追加"):
            item_name = discord.ui.TextInput(label="商品名（例: ラマロット）", placeholder="商品名を入力してください")
            stock_content = discord.ui.TextInput(
                label="中身（無限にしたい場合は先頭に 無限: ）", 
                style=discord.TextStyle.paragraph, 
                placeholder="例：無限:https://mediafire.com/... (無限在庫になります)"
            )
            async def on_submit(self, idx: discord.Interaction):
                d = load_data()
                if self.item_name.value not in d["items"]:
                    d["items"][self.item_name.value] = []
                d["items"][self.item_name.value].append(self.stock_content.value)
                save_data(d)
                await idx.response.send_message(f"📥 **{self.item_name.value}** に在庫を追加しました！", ephemeral=True)
        await interaction.response.send_modal(AddStockModal())

    @discord.ui.button(label="🗑️ 在庫・商品削除", style=discord.ButtonStyle.danger, row=0)
    async def del_item_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class DelItemModal(discord.ui.Modal, title="商品の削除"):
            item_name = discord.ui.TextInput(label="削除したい商品名", placeholder="完全に消去する商品名を入力")
            async def on_submit(self, idx: discord.Interaction):
                d = load_data()
                if self.item_name.value in d["items"]:
                    del d["items"][self.item_name.value]
                    save_data(d)
                    await idx.response.send_message(f"🗑️ **{self.item_name.value}** を削除しました。", ephemeral=True)
                else:
                    await idx.response.send_message("❌ その商品名は見つかりませんでした。", ephemeral=True)
        await interaction.response.send_modal(DelItemModal())

    @discord.ui.button(label="📝 タイトル設定", style=discord.ButtonStyle.secondary, row=1)
    async def set_title_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class TitleModal(discord.ui.Modal, title="タイトルの変更"):
            title = discord.ui.TextInput(label="パネルのタイトル", placeholder="例: 🛒 自動自販機パネル")
            async def on_submit(self, idx: discord.Interaction):
                d = load_data()
                d["config"]["title"] = self.title.value
                save_data(d)
                await idx.response.send_message("✏️ タイトルを更新しました！パネルを再作成すると反映されます。", ephemeral=True)
        await interaction.response.send_modal(TitleModal())

    @discord.ui.button(label="📄 パネル説明文", style=discord.ButtonStyle.secondary, row=1)
    async def set_desc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class DescModal(discord.ui.Modal, title="説明文の変更"):
            desc = discord.ui.TextInput(label="パネルの説明文", style=discord.TextStyle.paragraph, placeholder="説明文を入力してください")
            async def on_submit(self, idx: discord.Interaction):
                d = load_data()
                d["config"]["description"] = self.desc.value
                save_data(d)
                await idx.response.send_message("✏️ 説明文を更新しました！パネルを再作成すると反映されます。", ephemeral=True)
        await interaction.response.send_modal(DescModal())

    @discord.ui.button(label="🖼️ 画像設定", style=discord.ButtonStyle.secondary, row=2)
    async def set_image_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ImageModal(discord.ui.Modal, title="画像URLの設定"):
            url = discord.ui.TextInput(label="画像のURL", placeholder="https://から始まるリンク", required=False)
            async def on_submit(self, idx: discord.Interaction):
                d = load_data()
                d["config"]["image_url"] = self.url.value
                save_data(d)
                await idx.response.send_message("🖼️ 画像設定を更新しました！パネルを再作成すると反映されます。", ephemeral=True)
        await interaction.response.send_modal(ImageModal())

    @discord.ui.button(label="⭐ 実績記入設定", style=discord.ButtonStyle.secondary, row=2)
    async def set_proof_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class ProofModal(discord.ui.Modal, title="実績チャンネルの設定"):
            channel_id = discord.ui.TextInput(label="チャンネルID（数字のみ）", placeholder="例: 1511448796964454421", required=False)
            async def on_submit(self, idx: discord.Interaction):
                d = load_data()
                if self.channel_id.value:
                    d["config"]["proof_channel_id"] = self.channel_id.value
                    await idx.response.send_message("⭐ 実績ログの送信先を設定しました！", ephemeral=True)
                else:
                    d["config"]["proof_channel_id"] = None
                    await idx.response.send_message("⭐ 実績ログをオフにしました。", ephemeral=True)
                save_data(d)
        await interaction.response.send_modal(ProofModal())

# --- スラッシュコマンド ---

@bot.tree.command(name="自販機作成", description="最新の設定で自販機パネルをこのチャンネルに設置します")
@app_commands.checks.has_permissions(administrator=True)
async def create_vending(interaction: discord.Interaction):
    data = load_data()
    view = VendingView()
    
    embed = discord.Embed(
        title=data["config"]["title"],
        description=data["config"]["description"],
        color=discord.Color.green()
    )
    
    if data["items"]:
        for item, stocks in data["items"].items():
            # 在庫の中身が「無限:」から始まっている場合は、パネル上の表示を「無限」にする
            if stocks and stocks[0].startswith("無限:"):
                embed.add_field(name=item, value="在庫数: `無限`", inline=False)
            else:
                embed.add_field(name=item, value=f"在庫数: `{len(stocks)}`", inline=False)
    else:
        embed.description += "\n\n※商品が未登録です。`/自販機設定` から追加してください。"

    if data["config"].get("image_url"):
        embed.set_image(url=data["config"]["image_url"])

    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="自販機設定", description="自販機の管理メニューを開きます")
@app_commands.checks.has_permissions(administrator=True)
async def config_vending(interaction: discord.Interaction):
    view = ConfigView()
    embed = discord.Embed(
        title="🔧 自販機 管理・設定メニュー",
        description="下のボタンを押して設定を変更してください。\n※あなた（管理者）にしか見えません。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("ボットが稼働中です！".encode("utf-8"))

def run_http_server():
    server = HTTPServer(("0.0.0.0", int(os.getenv("PORT", 10000))), KeepAliveHandler)
    server.serve_forever()

@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user.name}")

if TOKEN:
    threading.Thread(target=run_http_server, daemon=True).start()
    bot.run(TOKEN)
else:
    print("エラー: DISCORD_TOKEN が設定されていません。")
