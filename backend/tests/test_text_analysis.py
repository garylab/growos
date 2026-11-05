from app.services.text_analysis import detect_intent, extract_mentions, lexicon_sentiment


BRAND = ("Hirelala", ["hirelala.com"])
COMPS = [("MockReal", ["mockreal.com"]), ("Interviewing.io", [])]


def test_extract_positions_and_counts():
    text = "For interview practice, MockReal is great. Hirelala is also solid, and hirelala.com has a free tier. MockReal again."
    ms = extract_mentions(text, BRAND, COMPS)
    names = [(m.entity_name, m.position, m.mention_count) for m in ms]
    assert names == [("MockReal", 1, 2), ("Hirelala", 2, 2)]
    assert ms[0].entity_type == "competitor" and ms[1].entity_type == "brand"


def test_word_boundaries_and_case():
    assert extract_mentions("I love HIRELALA!", BRAND, COMPS)[0].entity_name == "Hirelala"
    assert extract_mentions("hirelalaxyz is unrelated", BRAND, COMPS) == []
    assert extract_mentions("nothing here", BRAND, COMPS) == []


def test_list_rank_numbered_and_bulleted():
    text = "Top tools:\n1. MockReal - mock interviews\n2. Hirelala - AI practice\n3. Interviewing.io"
    ms = {m.entity_name: m for m in extract_mentions(text, BRAND, COMPS)}
    assert ms["MockReal"].list_rank == 1 and ms["Hirelala"].list_rank == 2 and ms["Interviewing.io"].list_rank == 3
    text2 = "Options:\n- Interviewing.io\n- MockReal\n- Hirelala"
    ms2 = {m.entity_name: m for m in extract_mentions(text2, BRAND, COMPS)}
    assert ms2["Hirelala"].list_rank == 3 and ms2["MockReal"].list_rank == 2


def test_sentiment_lexicon():
    assert lexicon_sentiment("Hirelala is excellent and easy to use") == "positive"
    assert lexicon_sentiment("Hirelala is buggy and expensive") == "negative"
    assert lexicon_sentiment("Hirelala is not good") == "negative"
    assert lexicon_sentiment("Hirelala exists") == "neutral"


def test_intent_detection():
    assert detect_intent("Any recommendations for a mock interview tool?") == "recommendation_request"
    assert detect_intent("How much does Hirelala pricing cost per month") == "purchase_intent"
    assert detect_intent("Their support is terrible, I want a refund") == "complaint"
    assert detect_intent("Does anyone use this?") == "question"
    assert detect_intent("We shipped a new feature.") == "none"
