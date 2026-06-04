import discord
from discord.ext import commands
from discord import app_commands
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import os

# --- 設定項目 ---
TOKEN = os.getenv("DISCORD_TOKEN")

GIFT_MESSAGE = (
    "使用方法等わからない場合はhttps://discord.com/channels/1503433355981488218/1511448796964454421 "
    "お問い合わせチケットを作成してください\n"
    "[自動ラマロットをダウンロード](https://www.mediafire.com/file/bg32wfdv7abeg99/20260102-1128_ba44d0e685884253ac4f083bc9de410c.exe/file)"
)
# ---------------

# ★Renderの強制終了を防ぐための常時起動用Webサーバー
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is running!")

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

# --- お客さんが使う「購入用」のビュー ---
class DistributeView(discord.ui.View):
    def __init__(self, log_channel_id: int = None):
        super().__init__(timeout=None)
        self.log_channel_id = log_channel_id

    @discord.ui.button(label="無料で受け取る🎁", style=discord.ButtonStyle.green, custom_id="free_get_button")
    async def get_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        panel_title = "商品"
        if interaction.message and interaction.message.embeds:
            panel_title = interaction.message.embeds[0].title

        success_embed = discord.Embed(
            title="🎁 商品の受け取り成功！",
            description=f"あなた専用の商品内容です。\n\n**【内容】**\n{GIFT_MESSAGE}",
            color=discord.Color.green()
        )

        try:
            # 商品内容をDMに送信（実績案内の文章は完全に削除されています）
            await interaction.user.send(embed=success_embed)
        except discord.Forbidden:
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            await interaction.followup.send("⚠️ DMが閉じられているため、画面上のみの表示となります。メモ等にお控えください。", ephemeral=True)
            return

        target_channel = interaction.channel
        if self.log_channel_id:
            chan = interaction.guild.get_channel(self.log_channel_id)
            if chan:
                target_channel = chan

        user = interaction.user
        log_text = (
            f"🎉 **購入者:** {user.mention}\n"
            f"👤 **ユーザー名:** `{user.name}`\n"
            f"🆔 **ユーザーID:** `{user.id}`\n\n"
            f"📦 **購入商品:** **{panel_title}** を購入（受け取り）しました！"
        )

        buy_embed = discord.Embed(description=log_text, color=discord.Color.gold())
        await target_channel.send(embed=buy_embed)


# --- 管理者が使う「自販機設定（リモコン）」用のビュー ---
class ConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🛒 パネルを新規作成する", style=discord.ButtonStyle.blurple, custom_id="btn_create_panel")
    async def create_panel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        # ボタンを押したときに浮き出る入力フォーム（Modal）
        class PanelFormModal(discord.ui.Modal, title="自販機パネルの作成"):
            panel_title = discord.ui.TextInput(label="パネルのタイトル", placeholder="例: 🛒 自動自販機パネル")
            panel_desc = discord.ui.TextInput(label="説明文", style=discord.TextStyle.paragraph, placeholder="商品の説明や規約を入力してください", required=False)
            panel_image = discord.ui.TextInput(label="画像URL（省略可能）", placeholder="https://... から始まるURL", required=False)
            panel_log = discord.ui.TextInput(label="通知チャンネルID（省略可能）", placeholder="購入通知を流したいチャンネルの数字ID", required=False)

            async def on_submit(self, idx: discord.Interaction):
                await idx.response.send_message("⚙️ パネルを設置しました！", ephemeral=True)
                
                # 緑固定で埋め込みを作成
                embed = discord.Embed(title=self.panel_title.value, color=discord.Color.green())
                
                if self.panel_desc.value:
                    embed.description = self.panel_desc.value.replace("\\n", "\n")
                if self.panel_image.value:
                    embed.set_image(url=self.panel_image.value)
                
                log_id = None
                if self.panel_log.value:
                    try:
                        log_id = int(self.panel_log.value)
                    except ValueError:
                        pass
                
                # 現在のチャンネルに自販機パネルを送信
                await idx.channel.send(embed=embed, view=DistributeView(log_channel_id=log_id))

        await interaction.response.send_modal(PanelFormModal())


# --- スラッシュコマンド ---

@bot.tree.command(name="自販機設定", description="自販機パネルを作成するための管理リモコン（ボタン）を開きます")
@app_commands.default_permissions(administrator=True)
async def config_vending(interaction: discord.Interaction):
    view = ConfigView()
    embed = discord.Embed(
        title="🔧 自販機 管理リモコン",
        description="下のボタンを押すと、パネル作成用のフォームが開きます。\n※あなた（管理者）にしか見えません。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="自販機作成", description="（予備）自販機設定と同じリモコンを開きます")
@app_commands.default_permissions(administrator=True)
async def create_vending(interaction: discord.Interaction):
    view = ConfigView()
    embed = discord.Embed(
        title="🔧 自販機 管理リモコン",
        description="下のボタンを押すと、パネル作成用のフォームが開きます。\n※あなた（管理者）にしか見えません。",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.event
async def on_ready():
    bot.add_view(DistributeView())
    bot.add_view(ConfigView())
    print(f"ログインしました: {bot.user.name}")

# Webサーバーを別スレッドで起動してからBOTを起動
threading.Thread(target=run_web_server, daemon=True).start()
bot.run(TOKEN)
