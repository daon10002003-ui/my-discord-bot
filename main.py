import discord
from discord.ext import commands
from discord import app_commands
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# --- 設定項目 ---
TOKEN = os.getenv("DISCORD_TOKEN")  # ←こう書けばGitHubにパスワードがバレません！

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
            await interaction.user.send(embed=success_embed)
            proof_channel = discord.utils.get(interaction.guild.channels, name="実績")
            if proof_channel:
                await interaction.user.send(f"✍️ ぜひ {proof_channel.mention} に実績の記入をお願いします！")
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

@bot.tree.command(name="setup_panel", description="配布パネルを設置・編集します")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(title="パネルのタイトル", description="パネルの説明文（省略可能）", image_url="画像のURL（省略可能）", log_channel="購入通知を送信するチャンネル", color="色(赤,緑,青,金)")
async def setup_panel(interaction: discord.Interaction, title: str, description: str = None, image_url: str = None, log_channel: discord.TextChannel = None, color: str = "緑"):
    await interaction.response.send_message("⚙️ パネルを設置しました！", ephemeral=True)
    color_dict = {"赤": discord.Color.red(), "緑": discord.Color.green(), "青": discord.Color.blue(), "金": discord.Color.gold()}
    embed_color = color_dict.get(color, discord.Color.green())
    embed = discord.Embed(title=title, color=embed_color)
    if description:
        embed.description = description.replace("\\n", "\n")
    if image_url:
        embed.set_image(url=image_url)
    log_id = log_channel.id if log_channel else None
    await interaction.channel.send(embed=embed, view=DistributeView(log_channel_id=log_id))

@bot.event
async def on_ready():
    bot.add_view(DistributeView())
    print(f"ログインしました: {bot.user.name}")

# Webサーバーを別スレッドで起動してからBOTを起動
threading.Thread(target=run_web_server, daemon=True).start()
bot.run(TOKEN)
