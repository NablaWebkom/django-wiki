from __future__ import print_function
from __future__ import absolute_import
from __future__ import unicode_literals

from django.core.management.base import BaseCommand, CommandError
import getpass


from wiki.models.article import ArticleRevision, ArticleForObject, Article
from wiki.models.urlpath import URLPath
from django.contrib.sites.models import Site
from django.contrib.auth import get_user_model 
from optparse import make_option
import string
from django.template.defaultfilters import slugify
from django.template.defaultfilters import striptags
import urllib
from urllib import parse
import six
import wikitools
from wikitools import wiki
from wikitools import category
import re


def only_printable(s):
    return ''.join([x for x in s if x in string.printable])


class Command(BaseCommand):
    help = 'Import everything from a MediaWiki'
    args = 'ApiUrl Username [Password]'

    articles_worked_on = []
    articles_imported = []
    matching_old_link_new_link = {}

    option_list = BaseCommand.option_list + (
        make_option(
            '--user-matching',
            action='append',
            dest='user_matching',
            default=[],
            help='List of <username>:django_user_pk to do the matchin'),
        make_option(
            '--replace_existing',
            action='store_true',
            dest='replace_existing',
            default=False,
            help='Replace existing pages'),
    )

    def get_params(self, args):
        """Return the list of params"""
        try:
            api_url = args[0]
        except IndexError:
            raise CommandError(
                'You need to provide the url to the MediaWiki API')

        try:
            api_username = args[1]
        except IndexError:
            raise CommandError('You need to provide an username')

        try:
            api_password = args[2]
        except IndexError:
            api_password = getpass.getpass('Please enter the API password: ')

            if not api_password:
                raise CommandError('You need to provide a password')

        return (api_url, api_username, api_password)

    def get_all_pages(self, api, site):
        """Return all pages on the wiki"""

        from wikitools.pagelist import listFromQuery

        result = api.APIRequest(
            site, {
                'action': 'query', 'generator': 'allpages'}).query()
                # 'action': 'query', 'titles': 'TFY4215 Innføring i kvantefysikk'}).query()

        return listFromQuery(site, result['query']['pages'])

    def get_all_categories(self, api, site):
        """Return all categories on the wiki"""

        result = api.APIRequest(
            site, {
                'action': 'query', 'generator': 'allcategories'}).query()

        return result['query']['pages']

    def import_page(
            self,
            api,
            site,
            page,
            current_site,
            url_root,
            user_matching,
            replace_existing,
            ):

        import pypandoc

        from wikitools.pagelist import listFromQuery



        # Filter titles, to avoid stranges charaters.
        title = page.title
        urltitle = title
        urltitle = urltitle.replace("ø", "o") 
        urltitle = urltitle.replace("æ", "ae") 
        urltitle = urltitle.replace("å", "a") 
        urltitle = urltitle.replace("Ø", "O") 
        urltitle = urltitle.replace("Æ", "AE") 
        urltitle = urltitle.replace("Å", "A") 
        urltitle = only_printable(urltitle)
        urltitle = slugify(only_printable(urllib.parse.unquote(urltitle))[:50])


        added = 1

        while urltitle in self.articles_worked_on:
            title = only_printable("{} {}".format(page.title, added))
            urltitle = slugify(
                "{} {}".format(only_printable(urllib.parse.unquote(page.urltitle))[:47], added)
            )

            added += 1

        self.articles_worked_on.append(urltitle)

        print("Working on {} ({})".format(title, urltitle))
        print(url_root)
        print(urltitle)
        print()
        # Check if the URL path already exists
        try:
            urlp = URLPath.objects.get(slug=urltitle)

            self.matching_old_link_new_link[
                page.title] = urlp.article.get_absolute_url()

            if not replace_existing:
                print("\tAlready existing, skipping...")
                return

            print("\tDestorying old version of the article")
            urlp.article.delete()

        except URLPath.DoesNotExist:
            pass

        # Create article
        article = Article()

        history_page = page.getHistory()[0]

        try:
            if history_page['user'] in user_matching:
                user = get_user_model().objects.get(
                    pk=user_matching[
                        history_page['user']])
            else:
                user = get_user_model().objects.get(
                    username=history_page['user'])
        except get_user_model().DoesNotExist:
            user = None
        except Exception:
            print("Couldn't find user. Something is weird.")

        article_revision = ArticleRevision()
        '''article_revision.content = pypandoc.convert(
            history_page['*'],
            'md',
            'mediawiki')
            '''
        article_revision.content = refactor(page.getWikiText())
        article_revision.title = title
        article_revision.user = user
        article_revision.owner = user
        article_revision.content = re.sub("\[\[.*(Category|Kategori).*\]\]\n", "", article_revision.content)

        article.add_revision(article_revision, save=True)

        article_revision.created = history_page['timestamp']
        article_revision.save()

        # Updated lastest content WITH expended templates
        # TODO ? Do that for history as well ?
        
        '''article_revision.content = pypandoc.convert(
            striptags(
                page.getWikiText(
                    True,
                    True)).replace(
                '__NOEDITSECTION__',
                '').replace(
                    '__NOTOC__',
                    ''),
            'md',
            'mediawiki')'''
        article_revision.save()

        article.save()

        upath = URLPath.objects.create(
            site=current_site,
            parent=url_root,
            slug=urltitle,
            article=article)
        article.add_object_relation(upath)

        self.matching_old_link_new_link[
            page.title] = upath.article.get_absolute_url()

        self.articles_imported.append((article, article_revision))

    def update_links(self):
        """Update link in imported articles"""

        # TODO: nsquare is bad
        for (article, article_revision) in self.articles_imported:
            print("Updating links of {}".format(article_revision.title))
            for id_from, id_to in six.iteritems(
                    self.matching_old_link_new_link):
                #print(
                    #"Replacing ({} \"wikilink\") with ({})".format(id_from, id_to)
                #)
                article_revision.content = article_revision.content.replace(
                    "({} \"wikilink\")".format(id_from),
                    "({})".format(id_to)
                )

            article_revision.save()

    def get_page_parent(self, page, available_cats, default, debug = False):
        text = page.getWikiText(True)
        if "#REDIRECT" in text or "#OMDIRIGERING" in text:
            return "ignore"
        m = re.findall("(\[\[.*(Kategori|Category).*\]\])", text)
        n = 0
        ret = default
        if m != []:
            for s in m:
                if type(s) == tuple:
                    s = s[0]
                tag = slugify(s.replace("ø", "o").replace("[[Kategori:", "").replace("[[Category:", "").replace("]]", "").split("|")[0]).replace("-", "_")
                if "fag" in tag:
                    tag = "fag"
                if tag in available_cats:
                    ret = tag
                    n += 1
            if debug:
                print(m)
        else:
            #if debug:
                #print(text)
            ret = default
        return ret
    def handle(self, *args, **options):

        try:
            import wikitools
        except ImportError:
            raise CommandError(
                'You need to install wikitools to use this command !')

        try:
            import pypandoc
        except ImportError:
            raise CommandError('You need to install pypandoc')

        user_matching = {}

        for um in options['user_matching']:
            mu = um[::-1]
            kp, emanresu = mu.split(':', 1)

            pk = kp[::-1]
            username = emanresu[::-1]

            user_matching[username] = pk

        api_url, api_username, api_password = self.get_params(args)

        site = wikitools.wiki.Wiki(api_url)
        site.login(api_username, api_password)

        pages = self.get_all_pages(wikitools.api, site)[:10]

        current_site = Site.objects.get_current()
        url_root = URLPath.root()
        print(url_root)

        oldpaths= [article.urlpath_set.all()[0] for article in Article.objects.all() if article.urlpath_set.all()[0].path.count("/") < 3]

        images = wikitools.api.APIRequest(
            site, {
                'action': 'query', 'list': 'allimages',
                'aiprop': 'url'}
            ).query()

        for image in images['query']['allimages']:
            print(image['url'])

        for page in pages:
            #root = self.get_page_parent(page, ["boker", "diverse", "fag/alle_fag", "folk", "foreninger_og_organisasjoner", "studieprogrammer", "utveksling_info", "utveksling_info/universiteter", "studieteknisk"], "diverse")
            root = self.get_page_parent(page, ["fag", "boker"], "diverse")

            if root != "ignore":

                for path in oldpaths:
                    if path.path == root + "/":
                        url_root = path
                        break

                self.import_page(
                    wikitools.api,
                    site,
                    page,
                    current_site,
                    url_root,
                    user_matching,
                    options['replace_existing'])

        self.update_links()

def refactor(s):
    result = s
    
    result = re.sub("\*([^ ])", r"* \1", result) # lists
    result = re.sub("'''", "**", result) # emphasis
    result = re.sub("(?<!\[)\[([^ \[]+) ([^\]]+)\](?!\])", r"[\2](\1)", result) # weblinks
    result = re.sub("\[\[Bilde:(.+\..+)\|(\d+)px\|(.+)\|(.+)\|(.+)\]\]", r"[image:1 align:\3 width:\2]\n\t\5\n", result) # images
    for i in range(6, 1, -1):
        result = re.sub("=" * i + " (.+) " + "=" * i, "#" * i + r" \1", result) # headers
    result = re.sub(":<math>(.+?)<\/math> ?[,\.]?", r"\n$$ \1 $$\n$~$\n", result) # latex stor
    result = re.sub("<math>(.+?)<\/math>", r"$ \1 $", result) # latex inline
    result = re.sub("\[\[(Kategori|Category).*\]\]", "", result)
    result = re.sub(re.compile("\<del\>(.*)\<\/del\>", re.DOTALL), r"(Utdatert) \1", result)
    result = re.sub("{{Boklink\|forfatter=([^|]+)\|tittel=([^}]+)}}", r"[\1: *\2*]([\1: \2])", result) # booklinks, TODO fix

    # info table
    lines = result.split("\n")
    
    tableCount = 0
    infoTable = []
    poemlines = ""
    for i in range(len(lines)):
        if "{{" in lines[i]:
            lines[i] = re.sub("{{Faginfo.*", "", lines[i])
            tableCount += 1

            for j in range(i + 1, len(lines)):
                line = lines[j]
                pairs = line.split("|")
                for pair in pairs:
                    if "=" not in pair:
                        continue
                    fields = pair.split("=")
                    if fields[0] == "fork":
                        continue

                    fields[0] = fields[0].replace("kode", "Fagkode")
                    fields[0] = fields[0].replace("navn", "Navn")
                    fields[0] = fields[0].replace("obl", "Obligatorisk for")
                    fields[0] = fields[0].replace("foreleser", "Foreleser")
                    fields[0] = fields[0].replace("lab", "Lab")
                    fields[0] = fields[0].replace("bok", "Lærebok")
                    fields[0] = fields[0].replace("ov", "Øvinger")
                    fields[0] = fields[0].replace("eksamen", "Eksamen")
                    fields[0] = fields[0].replace("nettside", "Nettside")
                    fields[1] = re.sub("(?:Nettside \| )(https?:\/\/)?(www\.)?[-øæåØÆÅa-zA-Z0-9@:%._\+~#=]{2,256}\.[øæåØÆÅa-z]{2,6}([-a-zøæåØÆÅA-Z0-9@:%_\+.~#?&\/\/=]*)", r"<\1>", fields[1])
                    infoTable.append((fields[0], fields[1]))

                if "}}" in line:
                    break;

        if "<blockquote><poem>" in lines[i]:
            for j in range(i, len(lines)):
                poemlines += re.sub("(\<\/?poem\>)?\<\/?blockquote\>(\<\/?poem\>)?", "", lines[j]) + "  \n"

                if "</poem></blockquote>" in lines[j]:
                    break;

    if poemlines != "":
        result = re.sub(re.compile("\<blockquote\>\<poem\>.*\<\/poem\>\<\/blockquote\>", re.DOTALL), poemlines, result)
    if tableCount > 0:
        fagkode = ""
        for info in infoTable:
            if info[0] == "Fagkode":
                fagkode = info[1]
                break
        tableString = "Fakta|%s\n" % fagkode
        tableString += "---|---\n"

        for info in infoTable[1:]:
            tableString += " %s | %s\n" % (info[0], info[1])
        tableString += "\n"

        result = re.sub(re.compile("{{Faginfo.*?}}", re.DOTALL), tableString, result)

    return result
